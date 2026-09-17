#!/usr/bin/env python3
"""Finalize a historical-only common-snapshot scan with repository-level counts."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--protocol", type=Path, required=True)
    ap.add_argument("--rows", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--prior-count", type=int, default=5)
    ap.add_argument("--output-prefix", type=Path, required=True)
    args = ap.parse_args()
    pairs = {x["pair_id"]: x for x in read_jsonl(args.pairs)}
    raw = [row for p in args.rows for row in read_jsonl(p)]
    dedup = {x["preflight_key"]: x for x in raw}
    eligible = [x for x in dedup.values() if x.get("eligible_state") is True]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in eligible:
        grouped[row["anchor_id"]].append(row)
    selected = []
    for anchor, choices in grouped.items():
        selected.append(min(choices, key=lambda x: hashlib.sha256(
            f"{args.seed}:{x['pair_id']}".encode()).hexdigest()))
    selected.sort(key=lambda x: x["anchor_id"])
    failure = Counter()
    for row in dedup.values():
        if row.get("eligible_state") is True:
            failure["eligible"] += 1
        elif row.get("fatal"):
            failure[row["fatal"]] += 1
        else:
            stage = "strict_gate_failed"
            for key in ("setup", "state_apply", "current_test", "future_gold_apply",
                        "future_test_apply", "future_fail_to_pass", "future_pass_to_pass",
                        "current_after_future"):
                value = row.get(key)
                if isinstance(value, dict) and value.get("returncode") not in (None, 0):
                    stage = key
                    break
            failure[stage] += 1
    expected = len(pairs)
    result = {
        "status": "GO" if len(selected) + args.prior_count >= 15 else "NO_GO",
        "protocol_id": json.loads(args.protocol.read_text())["protocol_id"],
        "expected_pairs": expected,
        "observed_unique_pairs": len(dedup),
        "physical_rows": len(raw),
        "complete": len(dedup) == expected,
        "eligible_pairs": len(eligible),
        "eligible_repositories": len(selected),
        "combined_repository_count": args.prior_count + len(selected),
        "selected": [{"anchor_id": x["anchor_id"], "pair_id": x["pair_id"]} for x in selected],
        "failure_counts": dict(sorted(failure.items())),
        "input_sha256": {str(p): sha(p) for p in [args.pairs, args.protocol, *args.rows]},
    }
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [f"# Historical-only common-snapshot scan", "",
             f"- Status: **{result['status']}**", f"- Complete: {result['observed_unique_pairs']}/{expected}",
             f"- Eligible pairs: {len(eligible)}", f"- Eligible repositories: {len(selected)}",
             f"- Combined repository count: {result['combined_repository_count']}", "", "## Selected", ""]
    lines += [f"- `{x['anchor_id']}` -> `{x['pair_id']}`" for x in selected]
    args.output_prefix.with_suffix(".md").write_text("\n".join(lines) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
