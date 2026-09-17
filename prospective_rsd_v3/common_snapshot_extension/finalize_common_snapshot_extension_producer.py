#!/usr/bin/env python3
"""Apply Protocol 32 candidate selection and freeze downstream extension rollout."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FREEZE = ROOT / "prospective_rsd_v3/continuation_freeze"
OUT = ROOT / "prospective_rsd_v3/extension_producer"


def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def main() -> None:
    pair_path = FREEZE / "common_snapshot_extension_selected_pairs_32.jsonl"
    pairs = {x["pair_id"]: x for x in rows(pair_path)}
    raw_paths = [OUT / "nugpu.jsonl", OUT / "yury.jsonl"]
    raw = [x for p in raw_paths for x in rows(p)]
    dedup = {x["rollout_key"]: x for x in raw}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in dedup.values():
        grouped[row["pair_id"]].append(row)
    selected = []
    exhausted_without_success = []
    for pair_id in sorted(pairs):
        successes = [x for x in grouped.get(pair_id, []) if x.get("current_success")]
        hashes = {x.get("candidate_hash") for x in successes}
        successes = sorted(successes, key=lambda x: x["attempt_index"])
        if successes:
            choice = dict(successes[0])
            choice["successful_unique_hashes_for_anchor"] = len(hashes)
            selected.append(choice)
        elif len({x.get("attempt_index") for x in grouped.get(pair_id, [])}) == 2:
            exhausted_without_success.append(pairs[pair_id]["anchor_id"])
    complete = len(dedup) == 2 * len(pairs)
    maximum_possible_new_repositories = len(pairs) - len(exhausted_without_success)
    early_no_go = maximum_possible_new_repositories < 10
    go = complete and len(selected) >= 10
    analysis = {
        "status": "GO" if go else ("EARLY_NO_GO_MATHEMATICALLY_DETERMINED" if early_no_go else "INCOMPLETE"),
        "complete": complete,
        "expected_attempts": 2 * len(pairs), "observed_attempts": len(dedup),
        "new_repositories_with_candidate": len(selected),
        "combined_repositories": 5 + len(selected),
        "repositories_with_both_attempts_failed": sorted(exhausted_without_success),
        "maximum_possible_new_repositories": maximum_possible_new_repositories,
        "maximum_possible_combined_repositories": 5 + maximum_possible_new_repositories,
        "stopping_reason": ("At least three repositories exhausted both frozen attempts without a success, "
                            "so the >=10/12 new-repository go rule cannot be met regardless of pending outcomes.")
                           if early_no_go and not complete else None,
        "selected": [{"anchor_id": x["anchor_id"], "pair_id": x["pair_id"],
                      "attempt_index": x["attempt_index"], "candidate_hash": x["candidate_hash"]}
                     for x in selected],
        "raw_sha256": {str(p): sha(p) for p in raw_paths if p.exists()},
    }
    dump(OUT / "producer_analysis_32.json", analysis)
    (OUT / "producer_analysis_32.md").write_text(
        "# Protocol 32 producer\n\n" +
        f"- Status: **{analysis['status']}**\n- Complete: {len(dedup)}/{2 * len(pairs)}\n" +
        f"- New repositories with a frozen current-success candidate: {len(selected)}/{len(pairs)}\n" +
        f"- Combined panel size: {5 + len(selected)} repositories\n")
    if not go:
        print(json.dumps(analysis, indent=2)); return
    cand_path = FREEZE / "common_snapshot_extension_candidates_33.jsonl"
    cand_path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in selected))
    arm_path = FREEZE / "common_snapshot_extension_arms_33.json"
    arms = {"arms": [{"future_pair_id": x["pair_id"], "anchor_id": x["anchor_id"],
                      "state_index": 0, "candidate_hash": x["candidate_hash"]} for x in selected]}
    dump(arm_path, arms)
    manifest = {
        "status": "FROZEN_BEFORE_ANY_EXTENSION_FUTURE_OUTCOMES",
        "eligible_future_pair_ids": [x["pair_id"] for x in selected],
        "selection_rule": "lowest attempt index among current-success candidates",
        "producer_analysis_sha256": sha(OUT / "producer_analysis_32.json"),
    }
    protocol = {
        "status": "FROZEN_BEFORE_ANY_EXTENSION_FUTURE_OUTCOMES",
        "date": "2026-09-10", "expected_states_per_pair": 2,
        "states": ["historical", "selected current-success candidate"],
        "repeat_indices": [0, 1, 2],
        "consumer": {"agent": "codex", "model": "gpt-5.6-sol", "effort": "medium"},
        "eligibility": {"minimum_eligible_future_pairs": 10},
        "primary": "joint future success with current FAIL_TO_PASS preservation",
        "inference": "average repeats within state, pair within repository; exact sign-flip and repository bootstrap",
        "candidate_outcomes_available_at_freeze": len(dedup),
        "future_outcomes_available_at_freeze": 0,
        "input_sha256": {"pairs": sha(pair_path), "candidates": sha(cand_path), "arms": sha(arm_path)},
    }
    protocol_id = hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()
    protocol["protocol_id"] = protocol_id; manifest["protocol_id"] = protocol_id
    dump(FREEZE / "common_snapshot_extension_future_protocol_33.json", protocol)
    dump(FREEZE / "common_snapshot_extension_manifest_33.json", manifest)
    print(json.dumps({**analysis, "protocol_id": protocol_id}, indent=2))


if __name__ == "__main__":
    main()
