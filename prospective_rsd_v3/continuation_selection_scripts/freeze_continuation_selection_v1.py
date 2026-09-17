#!/usr/bin/env python3
"""Freeze candidate states, selectors, held-out tasks, and analysis contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from continuation_selection_v1_tasks import HELDOUT_FUTURES, canonical_task_hash


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producers", nargs="+", required=True, type=Path)
    parser.add_argument("--development", nargs="+", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    producers = read_jsonl(args.producers)
    development = read_jsonl(args.development)
    states: dict[tuple[str, str], dict] = {}
    for row in producers:
        if not row.get("current_success"):
            continue
        key = (row["family"], row["source_sha256"])
        prior = states.get(key)
        if prior is None or (row["producer"], row["sample"]) < (prior["producer"], prior["sample"]):
            states[key] = row

    dedup_dev = {}
    for row in development:
        key = (row["consumer"], row["producer"], row["family"], row["producer_sample"],
               row["source_sha256"], row["future_id"])
        dedup_dev[key] = row
    grouped: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    for row in dedup_dev.values():
        grouped[(row["family"], row["source_sha256"], row["consumer"], row["future_id"])].append(
            float(row["future_success"])
        )

    state_rows = []
    by_family: dict[str, list[dict]] = defaultdict(list)
    for (family, state_hash), row in sorted(states.items()):
        cells = {(consumer, future): sum(vals) / len(vals)
                 for (fam, sha, consumer, future), vals in grouped.items()
                 if fam == family and sha == state_hash}
        expected_cells = {(r["consumer"], r["future_id"]) for r in development if r["family"] == family}
        if set(cells) != expected_cells:
            raise RuntimeError(f"Incomplete development panel for {family}/{state_hash}: {len(cells)} vs {len(expected_cells)}")
        item = {
            "family": family,
            "state_sha256": state_hash,
            "producer": row["producer"],
            "producer_sample": row["sample"],
            "source": row["source"],
            "source_chars": len(row["source"]),
            "features": row.get("features", {}),
            "development_cells": len(cells),
            "development_value": sum(cells.values()) / len(cells),
        }
        state_rows.append(item)
        by_family[family].append(item)

    if set(by_family) != set(HELDOUT_FUTURES):
        raise RuntimeError(f"Family mismatch: states={sorted(by_family)}, tasks={sorted(HELDOUT_FUTURES)}")

    selectors = {}
    for family, candidates in sorted(by_family.items()):
        continuation = min(candidates, key=lambda x: (-x["development_value"], x["state_sha256"]))
        shortest = min(candidates, key=lambda x: (x["source_chars"], x["state_sha256"]))
        selectors[family] = {
            "n_candidates": len(candidates),
            "continuation_selected_sha256": continuation["state_sha256"],
            "continuation_development_value": continuation["development_value"],
            "shortest_selected_sha256": shortest["state_sha256"],
            "shortest_source_chars": shortest["source_chars"],
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    states_path = args.output_dir / "frozen_states.jsonl"
    states_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in state_rows))
    selectors_path = args.output_dir / "frozen_selectors.json"
    selectors_path.write_text(json.dumps(selectors, indent=2, sort_keys=True) + "\n")
    tasks_path = args.output_dir / "frozen_heldout_tasks.json"
    tasks_path.write_text(json.dumps(HELDOUT_FUTURES, indent=2, sort_keys=True) + "\n")

    protocol = {
        "protocol": "continuation_aware_selection_v1",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "scientific_status": "prospective held-out outcomes; development outcomes already observed",
        "candidate_gate": "unique source_sha256 among naturally produced states that pass the current verifier and have all 12 development consumer-by-future cells",
        "development_panel": "four previously evaluated futures by three consumers; repeats collapsed within state-consumer-future before equal-cell averaging",
        "selectors": {
            "continuation": "maximum mean development continuation success within family; lexical SHA256 tie break",
            "current_success": "uniform random choice among all eligible current-success states within family; evaluated as the exact mean over all candidates",
            "static_shortest": "minimum source character count within family; lexical SHA256 tie break",
        },
        "heldout_panel": "two previously unexecuted future tasks per family",
        "consumer": "Qwen3-Coder-30B-A3B-Instruct",
        "consumer_disjoint_from_development": True,
        "consumer_precision": "bfloat16, one independently loaded model per shard",
        "execution_shards": 8,
        "repeats": 3,
        "seeds": [31001, 31002, 31003],
        "temperature": 0.2,
        "top_p": 0.95,
        "max_new_tokens": 900,
        "primary_estimand": "equal-family mean heldout success of continuation-selected state minus within-family mean over all current-success candidates",
        "secondary_estimands": [
            "continuation-selected minus static-shortest heldout success",
            "family-specific selection effects",
            "heldout regret relative to the post-hoc heldout oracle, reported only as an upper bound",
        ],
        "primary_inference": "exact random-selection distribution over one candidate per family, enumerated when feasible; family-cluster bootstrap interval as sensitivity analysis",
        "success_gate": "all frozen state-by-future-by-repeat keys present exactly once and all current-task tests preserved in the submitted module",
        "claim_gate": "decision utility supported only if the primary effect is positive and one-sided random-selection p < 0.05; otherwise report a completed no-go",
        "inputs": {str(p): sha256(p) for p in args.producers + args.development},
        "artifacts": {
            "states": sha256(states_path),
            "selectors": sha256(selectors_path),
            "tasks": sha256(tasks_path),
            "task_definition_module": canonical_task_hash(),
        },
        "counts": {
            "families": len(by_family),
            "states": len(state_rows),
            "heldout_futures": sum(len(v) for v in HELDOUT_FUTURES.values()),
            "planned_rollouts": len(state_rows) * 2 * 3,
        },
    }
    protocol_path = args.output_dir / "protocol.json"
    protocol_path.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"selectors": selectors, "counts": protocol["counts"], "protocol_sha256": sha256(protocol_path)}, indent=2))


if __name__ == "__main__":
    main()
