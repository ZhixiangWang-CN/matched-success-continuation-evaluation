#!/usr/bin/env python3
"""Validate and freeze formal control/continuation rows without outcome aggregation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def expected_keys(agent: str, protocol: dict, pairs: dict[str, dict], arms: list[dict]) -> set[str]:
    excluded = set(protocol["excluded_future_pair_ids"])
    eligible = [arm for arm in arms if arm["future_pair_id"] not in excluded]
    future_ids = sorted({arm["future_pair_id"] for arm in eligible})
    repeats = protocol["independent_repeats"]
    keys: set[str] = set()
    for future_pair_id in future_ids:
        pair = pairs[future_pair_id]
        for budget in protocol["historical_control_budgets"]:
            n_rep = 1 if budget == 0 else repeats
            for repeat in range(n_rep):
                state_id = f"historical_gold:{pair['anchor_id']}"
                keys.add(f"{future_pair_id}|{state_id}|{agent}|B{budget}|R{repeat}")
    budget = protocol["downstream_endpoint_budget"]
    for arm in eligible:
        for repeat in range(repeats):
            keys.add(f"{arm['arm_id']}|{agent}|B{budget}|R{repeat}|future")
    return keys


def validate_endpoint(row: dict) -> None:
    requested = row["future_endpoint_requested"]
    replay = bool(row.get("replay_success"))
    available = row.get("downstream_verifier_available")
    success = row.get("downstream_future_success")
    if not requested:
        assert available is None and success is None
    elif not replay:
        assert available is None and success is None
    elif available is True:
        assert isinstance(success, bool)
    else:
        assert available is False and success is None
    certified = bool(requested and replay and available is True and success is True)
    assert row["end_to_end_future_certified"] is certified


def validate_consumer(
    agent: str,
    model: str,
    base: Path,
    protocol: dict,
    pairs: dict[str, dict],
    arms: list[dict],
    require_complete: bool,
) -> tuple[list[dict], dict]:
    files = sorted(base.glob(f"{agent}_shard*.jsonl"))
    assert len(files) == 4, (agent, files)
    rows = [row for path in files for row in read_jsonl(path)]
    keys = [row["control_key"] for row in rows]
    expected = expected_keys(agent, protocol, pairs, arms)
    assert len(set(keys)) == len(keys)
    assert not (set(keys) - expected), {
        "missing": sorted(expected - set(keys)),
        "unexpected": sorted(set(keys) - expected),
    }
    if require_complete:
        assert set(keys) == expected, {"missing": sorted(expected - set(keys))}
    excluded = set(protocol["excluded_future_pair_ids"])
    infrastructure_errors = []
    for row in rows:
        assert row["agent"] == agent
        assert row["model"] == model
        assert row["protocol_id"] == protocol["protocol_id"]
        assert row["future_pair_id"] not in excluded
        assert row["state_type"] in {"historical", "candidate"}
        validate_endpoint(row)
        raw = json.dumps(row)
        fatal = str(row.get("fatal") or "")
        recovery_nonzero = any(
            round_.get("agent_returncode") not in (None, 0)
            for round_ in row.get("recovery_rounds") or []
        )
        future_nonzero = (
            row.get("future_endpoint_requested")
            and row.get("replay_success")
            and row.get("consumer_returncode") not in (None, 0)
        )
        unavailable = any(token in raw.lower() for token in (
            "not logged in", "session limit", "rate limit", "usage limit",
        ))
        if (fatal == "setup_failed" or fatal.startswith("FileNotFoundError:")
                or recovery_nonzero or future_nonzero or unavailable):
            infrastructure_errors.append(row["control_key"])
    assert not infrastructure_errors, infrastructure_errors
    rows.sort(key=lambda row: row["control_key"])
    summary = {
        "rows": len(rows),
        "unique_keys": len(set(keys)),
        "expected_rows": len(expected),
        "coverage": len(set(keys)) / len(expected),
        "missing_rows": len(expected - set(keys)),
        "missing_keys": sorted(expected - set(keys)),
        "historical_rows": sum(row["state_type"] == "historical" for row in rows),
        "candidate_rows": sum(row["state_type"] == "candidate" for row in rows),
        "future_requested": sum(bool(row["future_endpoint_requested"]) for row in rows),
        "infrastructure_errors": len(infrastructure_errors),
        "source_files": {path.name: sha256(path) for path in files},
    }
    if require_complete:
        assert summary["historical_rows"] == 299
        assert summary["candidate_rows"] == 138
        assert summary["future_requested"] == 207
    return rows, summary


def canonical_key(row: dict) -> str:
    marker = f"|{row['agent']}|"
    assert marker in row["control_key"]
    return row["control_key"].replace(marker, "|CONSUMER|", 1)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--pairs", type=Path, required=True)
    p.add_argument("--arms", type=Path, required=True)
    p.add_argument("--codex-dir", type=Path, required=True)
    p.add_argument("--claude-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    protocol = json.loads(args.protocol.read_text())
    pairs = {row["pair_id"]: row for row in read_jsonl(args.pairs)}
    arms = json.loads(args.arms.read_text())["arms"]
    consumers = {item["agent"]: item["model"] for item in protocol["consumers"]}
    codex, codex_summary = validate_consumer(
        "codex", consumers["codex"], args.codex_dir, protocol, pairs, arms, True)
    claude, claude_summary = validate_consumer(
        "claude", consumers["claude"], args.claude_dir, protocol, pairs, arms, False)
    assert len(claude) == 428

    codex_by_canonical = {canonical_key(row): row for row in codex}
    claude_canonical = {canonical_key(row) for row in claude}
    assert len(codex_by_canonical) == 437
    assert len(claude_canonical) == 428
    assert claude_canonical <= set(codex_by_canonical)
    paired_codex = [codex_by_canonical[key] for key in sorted(claude_canonical)]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    codex_path = args.output_dir / "codex_formal_437.jsonl"
    claude_path = args.output_dir / "claude_formal_428.jsonl"
    paired_path = args.output_dir / "paired_formal_856.jsonl"
    combined_path = args.output_dir / "combined_formal_865.jsonl"
    write_jsonl(codex_path, codex)
    write_jsonl(claude_path, claude)
    paired = sorted(paired_codex + claude, key=lambda row: (row["agent"], row["control_key"]))
    write_jsonl(paired_path, paired)
    combined = sorted(codex + claude, key=lambda row: (row["agent"], row["control_key"]))
    write_jsonl(combined_path, combined)

    manifest = {
        "status": "FROZEN_VALIDATED_CLAUDE_428_COMPLETE_CASE_RESULTS",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": sha256(args.protocol),
        "consumers": {"codex": codex_summary, "claude": claude_summary},
        "combined_rows": len(combined),
        "combined_unique_keys": len({row["control_key"] for row in combined}),
        "paired_rows": len(paired),
        "paired_canonical_keys": len(claude_canonical),
        "primary_analysis_population": "consumer-matched complete cases",
        "sensitivity_analysis_population": "all 437 Codex rows",
        "outputs": {
            codex_path.name: sha256(codex_path),
            claude_path.name: sha256(claude_path),
            paired_path.name: sha256(paired_path),
            combined_path.name: sha256(combined_path),
        },
    }
    assert manifest["combined_rows"] == manifest["combined_unique_keys"] == 865
    assert manifest["paired_rows"] == 856
    (args.output_dir / "formal_results_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
