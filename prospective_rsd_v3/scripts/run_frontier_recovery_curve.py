#!/usr/bin/env python3
"""Independent, pre-frozen recovery-budget sweep over fixed state--future arms."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
import uuid
from pathlib import Path

from frontier_proxy_server import serve
from run_frontier_conflict_recovery import execute_recovery, read_jsonl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--futures", required=True, type=Path)
    p.add_argument("--candidates", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--arms", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--logs", required=True, type=Path)
    p.add_argument("--agent", choices=["codex", "claude"], required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", default="medium")
    p.add_argument("--claude-host")
    p.add_argument("--proxy-port", type=int, default=18802)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "FROZEN_BEFORE_RECOVERY_CURVE_OUTCOMES":
        raise SystemExit("protocol is not frozen")
    pairs = {x["pair_id"]: x for x in read_jsonl(args.futures)}
    candidates = {x["candidate_hash"]: x for x in read_jsonl(args.candidates)}
    arms_doc = json.loads(args.arms.read_text())
    if arms_doc.get("protocol_id") != protocol["protocol_id"]:
        raise SystemExit("arms/protocol hash mismatch")

    budgets = protocol["budgets"]
    repeats = protocol["independent_repeats"]
    jobs = []
    for arm in arms_doc["arms"]:
        for budget in budgets:
            n_rep = 1 if budget == 0 else repeats
            for repeat in range(n_rep):
                key = f"{arm['arm_id']}|{args.agent}|B{budget}|R{repeat}"
                # Deterministic sharding is part of the frozen protocol.
                if int.from_bytes(key.encode(), "little") % args.num_shards != args.shard_index:
                    continue
                pair = pairs[arm["future_pair_id"]]
                candidate = candidates[arm["candidate_hash"]]
                replay = {
                    "current_base": pair["current"]["base_commit"],
                    "future_base": pair["future"]["base_commit"],
                    "integration_commit": protocol["integration_commits"][arm["anchor_id"]],
                    "candidate_patch": candidate["candidate_patch"],
                }
                meta = {
                    **arm,
                    "curve_key": key,
                    "recovery_budget": budget,
                    "independent_repeat": repeat,
                    "evaluation_split": "recovery_curve",
                    "protocol_id": protocol["protocol_id"],
                }
                jobs.append((key, pair, meta, replay, budget))

    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {x.get("curve_key") for x in previous}
    jobs = [x for x in jobs if x[0] not in done]
    if args.dry_run:
        print(json.dumps({
            "agent": args.agent, "shard_index": args.shard_index,
            "num_shards": args.num_shards, "pending_jobs": len(jobs),
            "by_budget": {str(b): sum(x[4] == b for x in jobs) for b in budgets},
        }, indent=2))
        return
    token = uuid.uuid4().hex if args.claude_host else None
    tunnel = None
    if args.claude_host:
        import subprocess
        threading.Thread(target=serve, args=(args.proxy_port, token), daemon=True).start()
        tunnel = subprocess.Popen([
            "ssh", "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ControlMaster=no",
            "-o", "ControlPath=none", "-R",
            f"127.0.0.1:{args.proxy_port}:127.0.0.1:{args.proxy_port}", args.claude_host,
        ])
        time.sleep(2)
        if tunnel.poll() is not None:
            raise SystemExit("reverse tunnel failed")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.logs.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("a") as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = {
                    pool.submit(
                        execute_recovery, pair, meta, replay, args.agent, args.model,
                        args.effort, args.logs, args.timeout, args.claude_host, token,
                        args.proxy_port, budget, False,
                    ): key for key, pair, meta, replay, budget in jobs
                }
                for future in concurrent.futures.as_completed(pending):
                    row = future.result()
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    print(json.dumps({
                        "key": row.get("curve_key"), "budget": row.get("recovery_budget"),
                        "recovered": row.get("verified_recovery"),
                        "rounds": len(row.get("recovery_rounds", [])),
                        "fatal": row.get("fatal"), "seconds": round(row.get("seconds", 0)),
                    }), flush=True)
    finally:
        if tunnel is not None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == "__main__":
    main()
