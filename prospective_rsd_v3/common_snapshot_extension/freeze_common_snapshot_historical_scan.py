#!/usr/bin/env python3
"""Freeze a within-repository historical-only feasibility scan after Protocol 29 no-go."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "real_repo_results/multifuture"
DEST = ROOT / "prospective_rsd_v3/continuation_freeze"
SEED = "common-snapshot-historical-scan-v1-20260910"
PRIOR = {"alteryx/woodwork", "getmoto/moto", "jsonpickle/jsonpickle",
         "kinto/kinto", "python-markdown/markdown"}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> str:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data); return sha_bytes(data)


def write_jsonl(path: Path, rows: list[dict]) -> str:
    data = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    path.write_bytes(data); return sha_bytes(data)


def main() -> None:
    valid_repos = {
        row["repo"] for row in json.loads((SRC / "summary.json").read_text())["rows"]
        if row["all_futures_eligible"] and row["repo"].lower() not in PRIOR
    }
    rows = [json.loads(line) for line in (SRC / "pairs.jsonl").read_text().splitlines()]
    rows = [{**row, "anchor_id": row["current"]["instance_id"]}
            for row in rows if row["repo"] in valid_repos]
    rows.sort(key=lambda row: (row["repo"].lower(), sha_bytes(f"{SEED}:{row['pair_id']}".encode())))
    pairs_path = DEST / "common_snapshot_historical_scan_pairs_30.jsonl"
    protocol_path = DEST / "common_snapshot_historical_scan_protocol_30.json"
    preflight_path = DEST / "common_snapshot_historical_scan_preflight_30.json"
    pairs_hash = write_jsonl(pairs_path, rows)
    protocol = {
        "status": "FROZEN_BEFORE_REMAINING_HISTORICAL_SCAN_AND_ANY_CANDIDATE_OUTCOMES",
        "date": "2026-09-10",
        "relationship_to_protocol_29": {
            "observed_before_freeze": "Protocol 29 historical-only preflight: 2/26 repositories passed for one hash-selected future.",
            "motivation": "The single-future screen was too sparse to meet the predeclared 15-repository threshold.",
            "unchanged": "Strict historical-only feasibility requirements and exclusion of candidate future outcomes.",
        },
        "population": "All 29 repositories outside the prior five whose complete future set was structurally valid in the earlier multi-future corpus; Protocol 29 hash-selected 26 of these.",
        "scan": {"future_pairs": len(rows), "repositories": len(valid_repos),
                 "selection_within_repository": f"Among strictly eligible historical arms, select minimum SHA256({SEED}:pair_id)."},
        "strict_gate": ["historical patch applies", "current FAIL_TO_PASS passes",
                        "future maintainer patch applies", "future tests apply",
                        "future FAIL_TO_PASS passes", "up to 20 future PASS_TO_PASS pass",
                        "current FAIL_TO_PASS remains passing"],
        "target": "retain at most 25 new repositories; combined with the prior five, continue only if total repository count is at least 15",
        "candidate_generation_and_future_rollout": "Remain exactly as frozen in Protocol 29 and begin only after this historical-only selection is sealed.",
        "candidate_outcomes_available_at_freeze": 0,
        "pairs_sha256": pairs_hash,
    }
    protocol_id = sha_bytes(json.dumps(protocol, sort_keys=True).encode())
    protocol["protocol_id"] = protocol_id
    write_json(protocol_path, protocol)
    write_json(preflight_path, {"status": "FROZEN_BEFORE_SYMMETRIC_PREFLIGHT_RESULTS",
                                "protocol_id": protocol_id,
                                "design": {"future_regression_cap": 20, "selection_arm": "historical only"}})
    print(json.dumps({"protocol_id": protocol_id, "repositories": len(valid_repos),
                      "future_pairs": len(rows), "pairs": str(pairs_path)}, indent=2))


if __name__ == "__main__":
    main()
