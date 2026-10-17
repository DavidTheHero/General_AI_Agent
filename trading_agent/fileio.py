"""Snapshot readers that allow atomic replacement while a reader is open."""
import os
from pathlib import Path

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL
    _kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  wintypes.LPVOID, wintypes.DWORD]
    _kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    _INVALID_HANDLE = ctypes.c_void_p(-1).value

    class _RenameInfo(ctypes.Structure):
        _fields_ = [("flags", wintypes.DWORD), ("root", wintypes.HANDLE),
                    ("length", wintypes.DWORD), ("name", ctypes.c_wchar * 1)]


def open_snapshot(path):
    """Open UTF-8 text; existing readers retain the old version after replace.

    The Windows CRT's default open omits FILE_SHARE_DELETE. Use a native
    read handle with read/write/delete sharing, retaining normal ACL checks.
    Ownership passes to the Python stream, which the caller must close.
    """
    if os.name != "nt":
        return Path(path).open(encoding="utf-8")
    handle = _kernel.CreateFileW(str(Path(path).resolve()), 0x80000000, 7, None, 3, 128, None)
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        _kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, "r", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def replace_snapshot(source, destination):
    """Atomically rename, including open delete-sharing readers on Windows.

    FileRenameInfoEx with REPLACE_IF_EXISTS | POSIX_SEMANTICS retains existing
    read handles on the old version. MoveFileEx (Python's os.replace) does not.
    Older Windows/filesystems fall back to os.replace and its bounded retries.
    """
    if os.name != "nt":
        return Path(source).replace(destination)
    name = str(Path(destination).resolve()).encode("utf-16-le")
    buffer = ctypes.create_string_buffer(ctypes.sizeof(_RenameInfo) + len(name))
    info = _RenameInfo.from_buffer(buffer)
    info.flags, info.root, info.length = 3, None, len(name)
    ctypes.memmove(ctypes.addressof(buffer) + _RenameInfo.name.offset, name, len(name))
    handle = _kernel.CreateFileW(str(Path(source).resolve()), 0x10000, 7, None, 3, 128, None)
    if handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not _kernel.SetFileInformationByHandle(handle, 22, buffer, len(buffer)):
            error = ctypes.get_last_error()
            if error not in {1, 50, 87}:  # Unsupported API/filesystem; preserve legacy behavior.
                raise ctypes.WinError(error)
        else:
            return
    finally:
        _kernel.CloseHandle(handle)
    return Path(source).replace(destination)
