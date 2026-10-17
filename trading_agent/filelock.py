"""Portable exclusive file lease used by the durable runtime.

POSIX keeps the historical ``fcntl.flock`` semantics. Windows has no flock,
so we hold a nonblocking exclusive lock on the first byte with ``msvcrt``.
The lock is bound to the file descriptor for its lifetime, released when the
descriptor closes (graceful close or process death), and never unlinks the
lock file on release.
"""
import errno
import os

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class LeaseBusy(Exception):
    """Raised when another owner already holds the exclusive lease."""


class FileLease:
    """Hold an exclusive nonblocking lock on a file for the object lifetime."""

    def __init__(self, path):
        self._fh = None
        try:
            self._fh = open(str(path), "a+b")
            if os.name == "nt":
                self._fh.seek(0)
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise LeaseBusy(str(path)) from None
                    raise
                # Windows can lock beyond EOF. Initialize only after ownership
                # so simultaneous first owners never write another owner's byte.
                if os.fstat(self._fh.fileno()).st_size == 0:
                    self._fh.write(b"\0")
                    self._fh.flush()
            else:
                try:
                    fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise LeaseBusy(str(path)) from None
                    raise
        except BaseException:
            self.release()
            raise

    def release(self):
        fh = self._fh
        self._fh = None
        if fh is not None:
            fh.close()

    def close(self):
        self.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
