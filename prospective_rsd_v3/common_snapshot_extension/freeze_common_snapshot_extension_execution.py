#!/usr/bin/env python3
"""Seal the repository-disjoint extension before any new candidate rollout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "prospective_rsd_v3/continuation_freeze"
SCAN = ROOT / "prospective_rsd_v3/extension_historical_scan"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    analyses = [json.loads((SCAN / f"analysis_{n}.json").read_text()) for n in (30, 31)]
    pair_sources = [FREEZE / "common_snapshot_historical_scan_pairs_30.jsonl",
                    FREEZE / "common_snapshot_broadened_scan_pairs_31.jsonl"]
    all_pairs = {}
    for path in pair_sources:
        for line in path.read_text().splitlines():
            row = json.loads(line); all_pairs[row["pair_id"]] = row
    chosen_ids = [x["pair_id"] for a in analyses for x in a["selected"]]
    selected = [all_pairs[x] for x in chosen_ids]
    selected.sort(key=lambda x: x["anchor_id"])
    pair_path = FREEZE / "common_snapshot_extension_selected_pairs_32.jsonl"
    pair_bytes = "".join(json.dumps(x, sort_keys=True) + "\n" for x in selected).encode()
    pair_path.write_bytes(pair_bytes)
    protocol = {
        "status": "FROZEN_BEFORE_ANY_EXTENSION_AGENT_OUTCOMES",
        "date": "2026-09-10",
        "objective": "Extend common-snapshot continuation from five to seventeen repository-disjoint anchors.",
        "relationship": "Twelve new anchors are the deterministic within-repository selections from completed historical-only Protocols 30 and 31; the prior five remain unchanged.",
        "candidate_outcomes_available_at_freeze": 0,
        "new_repositories": len(selected),
        "combined_repositories": len(selected) + 5,
        "producer": {"agent": "Codex", "model": "gpt-5.6-sol", "effort": "medium",
                     "independent_attempts_per_anchor": 2,
                     "information_boundary": "current issue and current repository snapshot only",
                     "network_in_container": False},
        "candidate_choice": "lowest attempt index among current-success candidates; never inspect future behavior",
        "current_success_gate": ["nonempty implementation diff", "no test-file edits",
                                 "current FAIL_TO_PASS passes", "up to 20 current PASS_TO_PASS tests pass",
                                 "unique normalized patch hash"],
        "future_rollout": {"consumer": "gpt-5.6-sol", "effort": "medium",
                           "repeats_per_state": 3,
                           "states": ["historical", "selected current-success candidate"],
                           "primary": "joint future success with current FAIL_TO_PASS preservation",
                           "inference": "average repeats within state, then paired repository effects; exact sign-flip and repository bootstrap"},
        "go_rule": "report the expanded panel only when at least ten of the twelve new repositories yield a current-success candidate, preserving at least fifteen total repositories",
        "pairs_sha256": sha(pair_bytes),
        "historical_analysis_sha256": {f"protocol_{n}": sha((SCAN / f"analysis_{n}.json").read_bytes()) for n in (30, 31)},
    }
    protocol["protocol_id"] = sha(json.dumps(protocol, sort_keys=True).encode())
    path = FREEZE / "common_snapshot_extension_execution_protocol_32.json"
    path.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"protocol_id": protocol["protocol_id"], "new_repositories": len(selected),
                      "combined_repositories": len(selected) + 5, "pairs": str(pair_path)}, indent=2))


if __name__ == "__main__":
    main()
