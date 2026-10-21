#!/usr/bin/env python3
"""Repair persisted-volume ownership, then run the gateway as the wb user."""

import os
import subprocess
import sys


APP_DIRS = ("/app/accounts", "/app/usage", "/app/data")
WB_UID = 100
WB_GID = 101


def main():
    if os.geteuid() == 0:
        for directory in APP_DIRS:
            os.makedirs(directory, exist_ok=True)
            result = subprocess.run(
                ["chown", "-R", f"{WB_UID}:{WB_GID}", directory],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode:
                print(
                    "entrypoint: could not repair %s ownership: %s"
                    % (directory, result.stderr.strip()),
                    file=sys.stderr,
                )
        os.setgroups([])
        os.setgid(WB_GID)
        os.setuid(WB_UID)

    args = sys.argv[1:]
    if args and not args[0].startswith("-"):
        os.execvp(args[0], args)
    os.execvp(
        "python",
        ["python", "/app/wb_proxy.py", *args],
    )


if __name__ == "__main__":
    main()
