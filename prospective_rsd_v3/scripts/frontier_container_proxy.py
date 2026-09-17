#!/usr/bin/env python3
"""Restricted local proxy for a frontier agent to operate one Docker container on yury."""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
from pathlib import Path


CONTAINER_RE = re.compile(r"^rsd-frontier-[A-Za-z0-9_.-]+$")


def validate(container: str, workdir: str) -> None:
    if not CONTAINER_RE.fullmatch(container):
        raise SystemExit("refusing non-frontier container")
    if not workdir.startswith("/") or ".." in Path(workdir).parts:
        raise SystemExit("invalid workdir")


def remote(args: list[str], *, input_text: str | None = None) -> int:
    command = args
    if os.environ.get("RSD_DOCKER_LOCAL") == "1":
        command = list(args)
        # Remote SSH needs shell-protection quotes around the `bash -lc`
        # payload; direct subprocess execution must remove that outer layer.
        if len(command) >= 2 and command[-2] == "-lc" and len(command[-1]) >= 2:
            if command[-1].startswith("'") and command[-1].endswith("'"):
                command[-1] = command[-1][1:-1]
    else:
        command = ["ssh", os.environ.get("RSD_DOCKER_HOST", "remote-host"), *args]
    proc = subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
    )
    sys.stdout.write(proc.stdout[-30000:])
    return proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("shell", "apply", "status"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--command")
    parser.add_argument("--patch", type=Path)
    parser.add_argument("--three-way", action="store_true")
    args = parser.parse_args()
    validate(args.container, args.workdir)

    if args.action == "shell":
        if not args.command:
            raise SystemExit("--command is required")
        encoded = base64.b64encode(args.command.encode()).decode()
        code = remote([
            "docker", "exec", "-w", args.workdir, args.container,
            "bash", "-lc", f"'echo {encoded} | base64 -d | bash'",
        ])
    elif args.action == "apply":
        if not args.patch or not args.patch.is_file():
            raise SystemExit("--patch must name a local diff file")
        patch = args.patch.read_text()
        copied = remote([
            "docker", "exec", "-i", args.container,
            "bash", "-lc", "'cat > /tmp/frontier-agent.patch'",
        ], input_text=patch)
        if copied:
            raise SystemExit(copied)
        apply_cmd = "git apply --whitespace=nowarn /tmp/frontier-agent.patch"
        if args.three_way:
            apply_cmd = (
                "if git apply --3way --check /tmp/frontier-agent.patch; then "
                "git apply --3way --whitespace=nowarn /tmp/frontier-agent.patch; "
                "elif git apply --check /tmp/frontier-agent.patch; then "
                "git apply --whitespace=nowarn /tmp/frontier-agent.patch; "
                "elif patch -p1 --dry-run --batch --forward --fuzz=3 "
                "< /tmp/frontier-agent.patch >/dev/null; then "
                "patch -p1 --batch --forward --fuzz=3 < /tmp/frontier-agent.patch; "
                "else git apply --reverse --check /tmp/frontier-agent.patch; fi"
            )
        code = remote([
            "docker", "exec", "-w", args.workdir, args.container,
            "bash", "-lc", (f"'{apply_cmd}'" if args.three_way else
                             f"'{apply_cmd} || git apply --reverse --check "
                             "/tmp/frontier-agent.patch'"),
        ])
    else:
        code = remote([
            "docker", "exec", "-w", args.workdir, args.container,
            "bash", "-lc", "'git status --short; git diff --stat; git diff --check'",
        ])
    raise SystemExit(code)


if __name__ == "__main__":
    main()
