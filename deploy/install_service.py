"""Generate or install macOS launch agents for the runtime and built web app."""
import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


def service(component, root):
    label = f"com.local.assistant.{component}"
    logs = root / "artifacts/trading/services"
    if component == "trading":
        command = [str(root / ".venv/bin/python"), "-m", "trading_agent.runtime"]
    else:
        node = shutil.which("node")
        if not node:
            raise ValueError("Install Node.js before installing the web service")
        command = [node, f"--env-file-if-exists={root / '.env'}", str(root / "backend/server.js")]
    environment = {"PYTHONUNBUFFERED": "1", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for key in ["TRADING_DATA_DIR", "TRADING_RUNTIME_PORT"]:
        if key in os.environ:
            environment[key] = os.environ[key]
    return {"Label": label, "ProgramArguments": command, "WorkingDirectory": str(root), "RunAtLoad": True,
            "KeepAlive": True, "ThrottleInterval": 10, "ExitTimeOut": 30, "EnvironmentVariables": environment,
            "StandardOutPath": str(logs / f"{component}.log"), "StandardErrorPath": str(logs / f"{component}.error.log")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["trading", "web"])
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--install", action="store_true", help="Install and start this user's macOS launch agent")
    flags.add_argument("--uninstall", action="store_true", help="Stop and remove this launch agent; preserve job data")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    specification = service(args.component, root)
    if not args.install and not args.uninstall:
        print(plistlib.dumps(specification).decode())
        return
    if sys.platform != "darwin":
        parser.error("Installation uses macOS launchd; use your OS process supervisor on other systems")
    domain = f"gui/{os.getuid()}"
    target = Path.home() / "Library/LaunchAgents" / f"{specification['Label']}.plist"
    if args.uninstall:
        subprocess.run(["launchctl", "bootout", f"{domain}/{specification['Label']}"], check=False)
        target.unlink(missing_ok=True)
        return
    if target.exists():
        parser.error(f"{target} already exists; uninstall this service before reinstalling")
    (root / "artifacts/trading/services").mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(specification))
    subprocess.run(["launchctl", "bootstrap", domain, str(target)], check=True)
    print(f"Started {specification['Label']}. Logs: {specification['StandardOutPath']}")


if __name__ == "__main__":
    main()
