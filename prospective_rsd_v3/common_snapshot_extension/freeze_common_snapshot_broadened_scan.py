#!/usr/bin/env python3
"""Freeze Protocol 31: historical-only scan in the preregistered broader cohort."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "real_repo_results/multifuture"
DEST = ROOT / "prospective_rsd_v3/continuation_freeze"
SEED = "common-snapshot-broadened-historical-scan-v1-20260910"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, obj, jsonl: bool = False) -> str:
    if jsonl:
        data = "".join(json.dumps(x, sort_keys=True) + "\n" for x in obj).encode()
    else:
        data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return digest(data)


def main() -> None:
    summaries = json.loads((SRC / "summary.json").read_text())["rows"]
    repos = {x["repo"] for x in summaries
             if x["eligible_future_tasks"] >= 3 and not x["all_futures_eligible"]}
    validation = {json.loads(x)["pair_id"]: json.loads(x)
                  for x in (SRC / "validation.jsonl").read_text().splitlines() if x.strip()}
    pairs = []
    for line in (SRC / "pairs.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["repo"] in repos and validation.get(row["pair_id"], {}).get("eligible"):
            pairs.append({**row, "anchor_id": row["current"]["instance_id"]})
    pairs.sort(key=lambda x: (x["repo"].lower(), digest(f"{SEED}:{x['pair_id']}".encode())))
    pairs_path = DEST / "common_snapshot_broadened_scan_pairs_31.jsonl"
    protocol_path = DEST / "common_snapshot_broadened_scan_protocol_31.json"
    preflight_path = DEST / "common_snapshot_broadened_scan_preflight_31.json"
    pairs_hash = write(pairs_path, pairs, jsonl=True)
    protocol = {
        "status": "FROZEN_BEFORE_BROADENED_HISTORICAL_SCAN_AND_ANY_CANDIDATE_OUTCOMES",
        "date": "2026-09-10",
        "relationship_to_protocol_30": {
            "observed_before_freeze": "Protocol 30 found nine new historically eligible repositories, yielding 14 repositories after combining the prior five, one below the predeclared threshold.",
            "motivation": "Evaluate the previously identified broader cohort without inspecting any candidate-state outcome.",
            "unchanged": "Strict historical-only feasibility gate, hash-based within-repository selection, candidate producer, and future rollout protocol.",
        },
        "population": "The nine repositories in the earlier multi-future corpus with at least three structurally valid futures but not an entirely valid future set.",
        "pair_inclusion": "Only pairs already marked eligible by the earlier structural validation; this precedes the stricter common-snapshot historical replay.",
        "scan": {
            "future_pairs": len(pairs),
            "repositories": len(repos),
            "selection_within_repository": f"Among strictly eligible historical arms, select minimum SHA256({SEED}:pair_id).",
        },
        "strict_gate": [
            "historical patch applies", "current FAIL_TO_PASS passes",
            "future maintainer patch applies", "future tests apply",
            "future FAIL_TO_PASS passes", "up to 20 future PASS_TO_PASS pass",
            "current FAIL_TO_PASS remains passing",
        ],
        "stopping_rule": "Combine with the prior five and Protocol 30 repositories; proceed only if at least 15 repository-disjoint anchors are available.",
        "candidate_outcomes_available_at_freeze": 0,
        "pairs_sha256": pairs_hash,
    }
    protocol_id = digest(json.dumps(protocol, sort_keys=True).encode())
    protocol["protocol_id"] = protocol_id
    write(protocol_path, protocol)
    write(preflight_path, {
        "status": "FROZEN_BEFORE_SYMMETRIC_PREFLIGHT_RESULTS",
        "protocol_id": protocol_id,
        "design": {"future_regression_cap": 20, "selection_arm": "historical only"},
    })
    print(json.dumps({"protocol_id": protocol_id, "repositories": len(repos),
                      "future_pairs": len(pairs), "pairs": str(pairs_path)}, indent=2))


if __name__ == "__main__":
    main()
