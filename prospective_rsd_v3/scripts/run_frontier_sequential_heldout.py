#!/usr/bin/env python3
"""Evaluate frozen historical/low/high states on frozen held-out futures."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from frontier_proxy_server import serve
from run_frontier_claude_calibration import execute_one


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--futures", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--replay-protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--logs", required=True, type=Path)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--claude-host")
    parser.add_argument("--proxy-port", type=int, default=18801)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    pairs = {row["pair_id"]: row for row in read_jsonl(args.futures)}
    candidates = {row["candidate_hash"]: row for row in read_jsonl(args.candidates)}
    selection = json.loads(args.selection.read_text())
    replay_protocol = json.loads(args.replay_protocol.read_text())
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {(row.get("future_pair_id"), row.get("candidate_id")) for row in previous}
    jobs = []
    for anchor_id, chosen in selection["anchors"].items():
        states = [("historical_gold", None, "historical")]
        for level in ("low", "high"):
            candidate_hash = chosen[f"{level}_candidate_hash"]
            states.append((chosen[f"{level}_candidate_id"], candidates[candidate_hash], level))
        for future_pair_id in chosen["future_pair_ids"]:
            pair = pairs[future_pair_id]
            for candidate_id, candidate, level in states:
                if (future_pair_id, candidate_id) in done:
                    continue
                metadata = {
                    "future_pair_id": future_pair_id, "candidate_id": candidate_id,
                    "candidate_hash": "historical_gold" if candidate is None else candidate["candidate_hash"],
                    "candidate_sample": None if candidate is None else candidate.get("sample"),
                    "state_level": level, "evaluation_split": "heldout",
                }
                replay_spec = None
                if candidate is not None:
                    replay_spec = {
                        "current_base": pair["current"]["base_commit"],
                        "future_base": pair["future"]["base_commit"],
                        "integration_commit": replay_protocol["integration_commits"][anchor_id],
                        "candidate_patch": candidate["candidate_patch"],
                    }
                jobs.append((pair, metadata, replay_spec))

    if args.claude_host and args.agent != "claude":
        raise SystemExit("--claude-host is valid only with --agent claude")
    if args.agent == "claude" and not args.claude_host:
        raise SystemExit("remote Claude replication requires --claude-host")
    proxy_token = uuid.uuid4().hex if args.claude_host else None
    tunnel = None
    if args.claude_host:
        threading.Thread(target=serve, args=(args.proxy_port, proxy_token), daemon=True).start()
        tunnel = subprocess.Popen([
            "ssh", "-N", "-o", "ExitOnForwardFailure=yes",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-R", f"127.0.0.1:{args.proxy_port}:127.0.0.1:{args.proxy_port}",
            args.claude_host,
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2)
        if tunnel.poll() is not None:
            detail = tunnel.stdout.read().decode(errors="replace") if tunnel.stdout else ""
            raise SystemExit(f"reverse tunnel failed to start: {detail[-2000:]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("a") as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = [pool.submit(
                    execute_one, pair, 0, args.agent, args.model, args.effort,
                    args.logs, args.timeout, args.claude_host, proxy_token,
                    args.proxy_port, None, metadata, replay_spec,
                ) for pair, metadata, replay_spec in jobs]
                for future in concurrent.futures.as_completed(pending):
                    row = future.result()
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    print(json.dumps({"anchor": row.get("anchor_id"),
                                      "future": row.get("future_pair_id"),
                                      "state": row.get("state_level"),
                                      "candidate": row.get("candidate_id"),
                                      "replay": row.get("replay_success"),
                                      "success": row.get("success"),
                                      "fatal": row.get("fatal")}), flush=True)
    finally:
        if tunnel is not None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == "__main__":
    main()
