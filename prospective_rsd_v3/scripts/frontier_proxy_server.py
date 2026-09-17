#!/usr/bin/env python3
"""Token-protected localhost HTTP bridge to the restricted yury container proxy."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from frontier_container_proxy import validate


def execute(action: str, payload: dict) -> dict:
    container, workdir = payload["container"], payload["workdir"]
    validate(container, workdir)
    if action == "shell":
        command = payload.get("command", "")
        if not command:
            return {"returncode": 2, "output": "missing command"}
        encoded = base64.b64encode(command.encode()).decode()
        remote = ["docker", "exec", "-w", workdir, container, "bash", "-lc",
                  f"'echo {encoded} | base64 -d | bash'"]
        input_text = None
    elif action == "apply":
        patch = payload.get("patch", "")
        copy = subprocess.run(
            ["ssh", "remote-host", "docker", "exec", "-i", container,
             "bash", "-lc", "'cat > /tmp/frontier-agent.patch'"],
            input=patch, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
        )
        if copy.returncode:
            return {"returncode": copy.returncode, "output": copy.stdout[-30000:]}
        apply_cmd = "git apply --whitespace=nowarn /tmp/frontier-agent.patch"
        if payload.get("three_way"):
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
        remote = ["docker", "exec", "-w", workdir, container, "bash", "-lc",
                  (f"'{apply_cmd}'" if payload.get("three_way") else
                   f"'{apply_cmd} || git apply --reverse --check "
                   "/tmp/frontier-agent.patch'")]
        input_text = None
    else:
        remote = ["docker", "exec", "-w", workdir, container, "bash", "-lc",
                  "'git status --short; git diff --stat; git diff --check'"]
        input_text = None
    proc = subprocess.run(["ssh", "remote-host", *remote], input=input_text, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    return {"returncode": proc.returncode, "output": proc.stdout[-30000:]}


def serve(port: int, token: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size))
                if payload.get("token") != token:
                    self.send_error(403)
                    return
                action = self.path.strip("/")
                if action not in {"shell", "apply", "status"}:
                    self.send_error(404)
                    return
                result = execute(action, payload)
                body = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"returncode": 70, "output": f"{type(exc).__name__}:{exc}"}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    serve(args.port, args.token)


if __name__ == "__main__":
    main()
