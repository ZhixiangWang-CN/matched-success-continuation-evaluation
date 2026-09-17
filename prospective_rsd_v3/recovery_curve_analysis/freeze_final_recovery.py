#!/usr/bin/env python3
"""Validate and fingerprint the final recovery-curve analysis inputs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "recovery_curve_data_manifest.json"
PROTOCOL = ROOT / "prospective_rsd_v3/continuation_freeze/recovery_curve_protocol_17.json"
INPUTS = [
    ROOT / "server_staging/prospective_rsd_v3/recovery_curve/claude_valid_v2_s0.jsonl",
    ROOT / "server_staging/prospective_rsd_v3/recovery_curve/claude_valid_v2_s1.jsonl",
    ROOT / "server_staging/prospective_rsd_v3/recovery_curve/codex_valid_v4_s0.jsonl",
    ROOT / "server_staging/prospective_rsd_v3/recovery_curve/codex_valid_v4_s1.jsonl",
]
FROZEN_SUPPORT = [
    ROOT / "prospective_rsd_v3/continuation_freeze/recovery_curve_arms_17.json",
    ROOT / "prospective_rsd_v3/continuation_freeze/recovery_curve_pairs_17.jsonl",
    ROOT / "prospective_rsd_v3/continuation_freeze/recovery_curve_candidates_17.jsonl",
]
EXPECTED_PROTOCOL_ID = "409635ca6866dc49501c63f4ff2e310e10f5084ef6362db844b1c755db2fc6a4"
EXCLUDED_ARMS = {
    "alteryx__woodwork-640|s0|alteryx__woodwork-687",
    "alteryx__woodwork-640|s1|alteryx__woodwork-687",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text())
    assert protocol["protocol_id"] == EXPECTED_PROTOCOL_ID
    files = []
    all_rows: list[dict] = []
    per_consumer = Counter()
    infra_by_consumer = Counter()
    for path in INPUTS:
        rows = load_jsonl(path)
        assert len(rows) == 312, (path, len(rows))
        assert all(row["protocol_id"] == EXPECTED_PROTOCOL_ID for row in rows)
        assert len({row["curve_key"] for row in rows}) == len(rows)
        all_rows.extend(rows)
        agent = rows[0]["agent"]
        per_consumer[agent] += len(rows)
        infra = [row for row in rows if row.get("fatal") == "replay_worktree_failed"]
        infra_by_consumer[agent] += len(infra)
        assert {row["arm_id"] for row in infra}.issubset(EXCLUDED_ARMS)
        files.append({"path": str(path.relative_to(ROOT)), "rows": len(rows), "sha256": sha256(path)})

    assert len({row["curve_key"] for row in all_rows}) == len(all_rows)
    assert per_consumer == {"claude": 624, "codex": 624}
    assert infra_by_consumer == {"claude": 26, "codex": 26}
    eligible = [row for row in all_rows if row.get("fatal") != "replay_worktree_failed"]
    arms_by_consumer = {
        agent: len({row["arm_id"] for row in eligible if row["agent"] == agent})
        for agent in ("claude", "codex")
    }
    assert arms_by_consumer == {"claude": 46, "codex": 46}
    manifest = {
        "status": "FROZEN_FINAL_ANALYSIS_INPUTS",
        "protocol_id": EXPECTED_PROTOCOL_ID,
        "input_files": files,
        "support_files": [
            {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for path in [PROTOCOL, *FROZEN_SUPPORT]
        ],
        "raw_rows_per_consumer": dict(per_consumer),
        "exclusion": {
            "reason": "replay_worktree_failed: container image lacks the frozen Git reference",
            "arms": sorted(EXCLUDED_ARMS),
            "rows_per_consumer": dict(infra_by_consumer),
        },
        "eligible_rows_per_consumer": {agent: 598 for agent in per_consumer},
        "eligible_arms_per_consumer": arms_by_consumer,
        "repository_count": len({row["repo"] for row in eligible}),
        "budgets": sorted({row["recovery_budget"] for row in eligible}),
        "repeat_rule": "B=0 has one deterministic row per arm; B>0 has three independent rows per arm.",
    }
    OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
