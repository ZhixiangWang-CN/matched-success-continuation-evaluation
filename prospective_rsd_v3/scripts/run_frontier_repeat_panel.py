#!/usr/bin/env python3
"""Execute the outcome-independent frozen repeat panel."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path

from audit_sequential_replay import execute as replay_once
from run_frontier_claude_calibration import execute_one


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_rows(output: Path, jobs, workers: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            pending = [pool.submit(fn, *args) for fn, args in jobs]
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                print(json.dumps({
                    "panel": row.get("repeat_panel"),
                    "anchor": row.get("anchor_id"),
                    "state": row.get("state_level"),
                    "candidate": row.get("candidate_id"),
                    "repeat": row.get("repeat_index"),
                    "replay": row.get("replay_success"),
                    "success": row.get("success"),
                    "fatal": row.get("fatal"),
                }), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--futures", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--replay-protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--mode", required=True, choices=["consumer", "deterministic"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    panel = json.loads(args.panel.read_text())
    pairs = {row["pair_id"]: row for row in read_jsonl(args.futures)}
    candidates = {row["candidate_hash"]: row for row in read_jsonl(args.candidates)}
    protocol = json.loads(args.replay_protocol.read_text())
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {(row.get("repeat_panel"), row.get("candidate_hash"), row.get("repeat_index"))
            for row in previous}
    jobs = []

    if args.mode == "consumer":
        spec = panel["stochastic_consumer_panel"]
        pair = pairs[spec["future_pair_id"]]
        for state_position, state in enumerate(spec["states"]):
            candidate_hash = state["candidate_hash"]
            candidate = None if candidate_hash == "historical_gold" else candidates[candidate_hash]
            level = ["historical", "low", "high"][state_position]
            for repeat_index in range(
                spec["existing_formal_rollouts_per_state"],
                spec["target_total_rollouts_per_state"],
            ):
                key = ("stochastic_consumer", candidate_hash, repeat_index)
                if key in done:
                    continue
                metadata = {
                    "repeat_panel": "stochastic_consumer",
                    "repeat_index": repeat_index,
                    "candidate_id": state["candidate_id"],
                    "candidate_hash": candidate_hash,
                    "state_level": level,
                    "evaluation_split": "audit_repeat",
                }
                replay_spec = None
                if candidate is not None:
                    replay_spec = {
                        "current_base": pair["current"]["base_commit"],
                        "future_base": pair["future"]["base_commit"],
                        "integration_commit": protocol["integration_commits"][spec["anchor_id"]],
                        "candidate_patch": candidate["candidate_patch"],
                    }
                jobs.append((execute_one, (
                    pair, repeat_index, "codex", args.model, args.effort,
                    args.logs or args.output.parent / "repeat_logs", args.timeout,
                    None, None, 0, None, metadata, replay_spec,
                )))
    else:
        for item in panel["deterministic_high_debt_replay_panel"]:
            anchor_id = item["anchor_id"]
            anchor = next(row for row in json.loads(
                Path("prospective_rsd_v3/continuation_freeze/eligible_anchors.json").read_text()
            ) if row["anchor_id"] == anchor_id)
            pair = pairs[anchor["audit_future_pair_id"]]
            candidate = candidates[item["candidate_hash"]]
            integration = protocol["integration_commits"][anchor_id]
            for repeat_index in range(item["target_replays"]):
                key = ("deterministic_replay", item["candidate_hash"], repeat_index)
                if key in done:
                    continue

                def tagged_replay(p=pair, c=candidate, i=integration,
                                  ri=repeat_index):
                    row = replay_once(p, c, i)
                    row.update({"repeat_panel": "deterministic_replay",
                                "repeat_index": ri, "state_level": "high"})
                    return row

                jobs.append((tagged_replay, ()))

    append_rows(args.output, jobs, args.workers)


if __name__ == "__main__":
    main()
