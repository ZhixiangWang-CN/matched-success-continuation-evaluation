#!/usr/bin/env python3
"""Freeze the repository-disjoint common-snapshot extension before new agent outcomes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "real_repo_results/multifuture"
DEST = ROOT / "prospective_rsd_v3/continuation_freeze"
SEED = "common-snapshot-extension-v1-20260910"
EXCLUDED = {
    "alteryx/woodwork", "getmoto/moto", "jsonpickle/jsonpickle",
    "kinto/kinto", "python-markdown/markdown",
}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    return digest_bytes(payload)


def write_jsonl(path: Path, rows: list[dict]) -> str:
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode()
    path.write_bytes(payload)
    return digest_bytes(payload)


def main() -> None:
    summaries = json.loads((SOURCE / "summary.json").read_text())["rows"]
    pairs = [json.loads(line) for line in (SOURCE / "pairs.jsonl").read_text().splitlines()]
    by_sequence: dict[str, list[dict]] = {}
    for pair in pairs:
        by_sequence.setdefault(pair["sequence_id"], []).append(pair)

    eligible = [row for row in summaries if row["all_futures_eligible"] and row["repo"].lower() not in EXCLUDED]
    eligible.sort(key=lambda row: digest_bytes(f"{SEED}:{row['repo'].lower()}".encode()))
    selected = eligible[:26]
    frozen_pairs = []
    for row in selected:
        candidates = sorted(by_sequence[row["sequence_id"]], key=lambda x: x["pair_id"])
        # Future identity is fixed by a content-blind hash; no patch, test, or result enters selection.
        pair = min(candidates, key=lambda x: digest_bytes(f"{SEED}:{x['pair_id']}".encode()))
        frozen_pairs.append({**pair, "anchor_id": pair["current"]["instance_id"],
                             "selection_rule": "hash-ranked repository and hash-ranked future identity"})

    pairs_path = DEST / "common_snapshot_extension_pairs_29.jsonl"
    pool_path = DEST / "common_snapshot_extension_pool_29.json"
    protocol_path = DEST / "common_snapshot_extension_protocol_29.json"
    preflight_path = DEST / "common_snapshot_extension_preflight_29.json"
    arms_path = DEST / "common_snapshot_extension_historical_arms_29.json"
    pairs_hash = write_jsonl(pairs_path, frozen_pairs)
    pool = {
        "status": "FROZEN_BEFORE_ANY_EXTENSION_AGENT_OUTCOMES",
        "seed": SEED,
        "source": "real_repo_results/multifuture summary and pairs",
        "source_population": {"repositories": 50, "all_future_valid": 31},
        "excluded_prior_common_snapshot_repositories": sorted(EXCLUDED),
        "candidate_pool_repositories": len(frozen_pairs),
        "pair_ids": [row["pair_id"] for row in frozen_pairs],
        "pairs_sha256": pairs_hash,
    }
    pool_hash = write_json(pool_path, pool)
    protocol = {
        "status": "FROZEN_BEFORE_ANY_EXTENSION_AGENT_OUTCOMES",
        "date": "2026-09-10",
        "objective": "Increase repository-level support for direct common-snapshot continuation effects.",
        "unit": "one historical and one independently produced current-success state crossed with one frozen future per repository",
        "selection": {
            "repository_pool": "All historically valid multi-future repositories except the five prior common-snapshot repositories.",
            "ranking": f"SHA256({SEED}:lowercase_repo), first 26",
            "future_identity": f"minimum SHA256({SEED}:pair_id) within each selected repository",
            "prohibited": ["candidate future diagnostics", "future-agent outcomes", "effect direction", "debt labels"],
        },
        "producer": {
            "agent": "Codex", "model": "gpt-5.6-sol", "effort": "medium",
            "independent_attempts_per_anchor": 2, "network_in_container": False,
            "information_boundary": "current issue and current repository snapshot only",
        },
        "current_success_gate": [
            "nonempty implementation diff", "no test-file edits", "current FAIL_TO_PASS passes",
            "up to 20 current PASS_TO_PASS tests pass", "unique normalized patch hash",
        ],
        "candidate_choice": "lowest attempt index among current-success candidates; never inspect future behavior",
        "historical_only_future_feasibility": [
            "historical patch applies and current FAIL_TO_PASS passes", "future maintainer patch applies",
            "future tests apply", "future FAIL_TO_PASS passes", "up to 20 future PASS_TO_PASS tests pass",
            "current FAIL_TO_PASS remains passing",
        ],
        "final_eligibility": "both current-success states exist and historical-only future feasibility passes",
        "go_rule": "at least 15 repository-disjoint eligible futures; otherwise report a completed no-go",
        "future_rollout": {
            "consumer": "gpt-5.6-sol", "effort": "medium", "repeats_per_state": 3,
            "primary": "joint future success with current FAIL_TO_PASS preservation",
            "inference": "average repeats within state, then paired repository effects; exact sign-flip and repository bootstrap",
        },
        "pool_sha256": pool_hash,
        "pairs_sha256": pairs_hash,
    }
    protocol_id = digest_bytes(json.dumps(protocol, sort_keys=True).encode())
    protocol["protocol_id"] = protocol_id
    write_json(protocol_path, protocol)
    write_json(preflight_path, {
        "status": "FROZEN_BEFORE_SYMMETRIC_PREFLIGHT_RESULTS",
        "protocol_id": protocol_id,
        "design": {"future_regression_cap": 20, "selection_arm": "historical only"},
    })
    write_json(arms_path, {"status": "FROZEN_HISTORICAL_ONLY_PREFLIGHT", "arms": [
        {"future_pair_id": row["pair_id"], "anchor_id": row["anchor_id"], "repo": row["repo"]}
        for row in frozen_pairs
    ]})
    print(json.dumps({"protocol_id": protocol_id, "repositories": len(frozen_pairs),
                      "pairs": str(pairs_path), "pool": str(pool_path)}, indent=2))


if __name__ == "__main__":
    main()
