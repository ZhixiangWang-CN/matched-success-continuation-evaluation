#!/usr/bin/env python3
"""CLI used by the remotely authenticated frontier agent through an SSH reverse tunnel."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("shell", "apply", "status"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--command")
    parser.add_argument("--patch", type=Path)
    parser.add_argument("--three-way", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("FRONTIER_PROXY_TOKEN")
    base = os.environ.get("FRONTIER_PROXY_URL", "http://127.0.0.1:18765")
    if not token:
        raise SystemExit("FRONTIER_PROXY_TOKEN is not set")
    payload = {"token": token, "container": args.container, "workdir": args.workdir}
    if args.command is not None:
        payload["command"] = args.command
    if args.patch is not None:
        payload["patch"] = args.patch.read_text()
    payload["three_way"] = args.three_way
    request = Request(base.rstrip("/") + "/" + args.action,
                      data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=700) as response:
        result = json.loads(response.read())
    sys.stdout.write(result.get("output", ""))
    raise SystemExit(int(result.get("returncode", 1)))


if __name__ == "__main__":
    main()
