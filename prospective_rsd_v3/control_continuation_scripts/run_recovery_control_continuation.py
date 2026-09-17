#!/usr/bin/env python3
"""Frozen historical-control curve and B=10 downstream-continuation endpoint."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

from frontier_proxy_server import serve
from run_frontier_conflict_recovery import execute_recovery, read_jsonl


def classify(row: dict, run_future: bool) -> dict:
    """Keep unavailable verifiers distinct from executed failures."""
    row["future_endpoint_requested"] = run_future
    prior_apply = row.get("prior_test_apply")
    prior_test = row.get("prior_task_test")
    row["endpoint_prior_verifier_available"] = (
        None if not run_future or not row.get("replay_success")
        else bool(prior_apply and prior_apply.get("returncode") == 0)
    )
    row["endpoint_prior_verifier_pass"] = (
        None if row["endpoint_prior_verifier_available"] is not True
        else bool(prior_test and prior_test.get("returncode") == 0)
    )

    hidden_apply = row.get("hidden_test_apply")
    hidden_available = bool(hidden_apply and hidden_apply.get("returncode") == 0)
    row["downstream_verifier_available"] = (
        None if not run_future or not row.get("replay_success") else hidden_available
    )
    if row["downstream_verifier_available"] is True:
        row["downstream_future_success"] = bool(
            row.get("successor_oracle_test", {}).get("returncode") == 0
            and row.get("successor_regression_test", {}).get("returncode") == 0
        )
    else:
        row["downstream_future_success"] = None

    # End-to-end lower bound counts inability to reach the future base as a
    # failure, but never turns verifier unavailability into behavioral failure.
    row["end_to_end_future_certified"] = bool(
        run_future and row.get("replay_success")
        and row["downstream_verifier_available"] is True
        and row["downstream_future_success"] is True
    )
    row["joint_prior_future_certified"] = bool(
        row["end_to_end_future_certified"]
        and row["endpoint_prior_verifier_available"] is True
        and row["endpoint_prior_verifier_pass"] is True
    )
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--futures", required=True, type=Path)
    p.add_argument("--candidates", required=True, type=Path)
    p.add_argument("--base-arms", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--logs", required=True, type=Path)
    p.add_argument("--agent", choices=["codex", "claude"], required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", default="medium")
    p.add_argument("--claude-host")
    p.add_argument("--proxy-port", type=int, default=18804)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--limit", type=int, default=None,
                   help="Optional staging-only cap applied after sharding and resume filtering.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "FROZEN_BEFORE_CONTROL_AND_CONTINUATION_OUTCOMES":
        raise SystemExit("control/continuation protocol is not frozen")
    pairs = {x["pair_id"]: x for x in read_jsonl(args.futures)}
    candidates = {x["candidate_hash"]: x for x in read_jsonl(args.candidates)}
    base_arms = json.loads(args.base_arms.read_text())["arms"]
    excluded = set(protocol["excluded_future_pair_ids"])
    eligible = [a for a in base_arms if a["future_pair_id"] not in excluded]
    future_ids = sorted({a["future_pair_id"] for a in eligible})
    assert len(eligible) == protocol["sample"]["alternative_arms"] == 46
    assert len(future_ids) == protocol["sample"]["historical_arms"] == 23

    jobs = []
    repeats = protocol["independent_repeats"]
    # Historical controls traverse the complete frozen budget curve. At B=10
    # the same independent executions continue into the future endpoint.
    for future_pair_id in future_ids:
        pair = pairs[future_pair_id]
        for budget in protocol["historical_control_budgets"]:
            n_rep = 1 if budget == 0 else repeats
            for repeat in range(n_rep):
                run_future = budget == protocol["downstream_endpoint_budget"]
                state_id = f"historical_gold:{pair['anchor_id']}"
                key = f"{future_pair_id}|{state_id}|{args.agent}|B{budget}|R{repeat}"
                replay = {
                    "current_base": pair["current"]["base_commit"],
                    "future_base": pair["future"]["base_commit"],
                    "integration_commit": protocol["integration_commits"][pair["anchor_id"]],
                    "candidate_patch": pair["current"]["patch"],
                }
                meta = {
                    "control_key": key, "state_type": "historical", "state_level": "historical",
                    "candidate_id": "historical_gold", "candidate_hash": "historical_gold",
                    "future_pair_id": future_pair_id, "recovery_budget": budget,
                    "independent_repeat": repeat, "protocol_id": protocol["protocol_id"],
                    "evaluation_split": "historical_control_curve_and_endpoint",
                }
                jobs.append((key, pair, meta, replay, budget, run_future))

    # Candidate states are rerun only at the pre-frozen downstream endpoint.
    budget = protocol["downstream_endpoint_budget"]
    for arm in eligible:
        pair = pairs[arm["future_pair_id"]]
        candidate = candidates[arm["candidate_hash"]]
        for repeat in range(repeats):
            key = f"{arm['arm_id']}|{args.agent}|B{budget}|R{repeat}|future"
            replay = {
                "current_base": pair["current"]["base_commit"],
                "future_base": pair["future"]["base_commit"],
                "integration_commit": protocol["integration_commits"][arm["anchor_id"]],
                "candidate_patch": candidate["candidate_patch"],
            }
            meta = {
                **arm, "control_key": key, "state_type": "candidate",
                "recovery_budget": budget, "independent_repeat": repeat,
                "protocol_id": protocol["protocol_id"],
                "evaluation_split": "candidate_downstream_endpoint",
            }
            jobs.append((key, pair, meta, replay, budget, True))

    jobs = [j for j in jobs if int.from_bytes(hashlib.sha256(j[0].encode()).digest()[:8], "big")
            % args.num_shards == args.shard_index]
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {x.get("control_key") for x in previous}
    jobs = [j for j in jobs if j[0] not in done]
    if args.limit is not None:
        jobs = jobs[:args.limit]
    if args.dry_run:
        print(json.dumps({
            "agent": args.agent, "pending_jobs": len(jobs),
            "historical": sum(j[2]["state_type"] == "historical" for j in jobs),
            "candidate_endpoint": sum(j[2]["state_type"] == "candidate" for j in jobs),
            "future_requested": sum(j[5] for j in jobs),
            "shard": [args.shard_index, args.num_shards],
        }, indent=2))
        return

    if args.claude_host and args.agent != "claude":
        raise SystemExit("--claude-host is valid only with --agent claude")
    token = uuid.uuid4().hex if args.claude_host else None
    tunnel = None
    if args.claude_host:
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
                    pool.submit(execute_recovery, pair, meta, replay, args.agent, args.model,
                                args.effort, args.logs, args.timeout, args.claude_host, token,
                                args.proxy_port, budget, run_future): (key, run_future)
                    for key, pair, meta, replay, budget, run_future in jobs
                }
                for future in concurrent.futures.as_completed(pending):
                    key, requested = pending[future]
                    row = classify(future.result(), requested)
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    print(json.dumps({
                        "key": key, "state": row.get("state_type"),
                        "budget": row.get("recovery_budget"), "replay": row.get("replay_success"),
                        "future": row.get("downstream_future_success"),
                        "future_verifier": row.get("downstream_verifier_available"),
                        "fatal": row.get("fatal"), "seconds": round(row.get("seconds", 0)),
                    }), flush=True)
    finally:
        if tunnel is not None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == "__main__":
    main()
