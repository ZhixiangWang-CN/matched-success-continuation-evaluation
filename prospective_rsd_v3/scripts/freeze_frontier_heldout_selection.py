#!/usr/bin/env python3
"""Freeze two generated states per anchor before opening held-out futures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def patch_churn(text: str) -> int:
    return sum(1 for line in text.splitlines()
               if (line.startswith("+") and not line.startswith("+++"))
               or (line.startswith("-") and not line.startswith("---")))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--replay", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    anchors = json.loads(args.anchors.read_text())
    candidates = {row["candidate_hash"]: row for row in read_jsonl(args.candidates)}
    replay = {row["candidate_hash"]: row for row in read_jsonl(args.replay)}
    audit = {row.get("candidate_hash"): row for row in read_jsonl(args.audit)
             if row.get("candidate_hash") not in {None, "historical_gold"}}
    output = {
        "status": "FROZEN_BEFORE_HELDOUT_ACCESS",
        "selection_rule": (
            "Within each anchor rank lexicographically by hard replay failure, metadata-conflict count, "
            "audit continuation failure, and frozen candidate-patch churn; choose minimum as low and "
            "maximum as high, breaking ties by candidate hash. Historical gold is always included."
        ),
        "arms_per_future": 3,
        "heldout_futures_per_anchor": 3,
        "total_heldout_arms": 45,
        "anchors": {},
        "source_hashes": {
            "anchors": sha256(args.anchors), "candidates": sha256(args.candidates),
            "replay": sha256(args.replay), "audit": sha256(args.audit),
        },
    }
    for anchor in anchors:
        rows = []
        for candidate in candidates.values():
            if candidate["anchor_id"] != anchor["anchor_id"]:
                continue
            rep = replay[candidate["candidate_hash"]]
            aud = audit.get(candidate["candidate_hash"], {})
            severity = [
                int(not rep.get("replay_success", False)),
                len(rep.get("metadata_conflicts", [])),
                int(aud.get("success") is not True),
                patch_churn(candidate["candidate_patch"]),
            ]
            rows.append((severity, candidate["candidate_hash"]))
        ranked = sorted(rows, key=lambda item: (item[0], item[1]))
        low, high = ranked[0], ranked[-1]
        output["anchors"][anchor["anchor_id"]] = {
            "future_pair_ids": anchor["heldout_future_pair_ids"],
            "historical_id": "historical_gold",
            "low_candidate_id": f"cand_{low[1][:12]}",
            "low_candidate_hash": low[1],
            "low_severity": low[0],
            "high_candidate_id": f"cand_{high[1][:12]}",
            "high_candidate_hash": high[1],
            "high_severity": high[0],
        }
    args.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
