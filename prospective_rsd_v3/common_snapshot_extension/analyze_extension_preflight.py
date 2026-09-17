#!/usr/bin/env python3
"""Summarize a frozen historical-only common-snapshot preflight."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from collections import Counter
from pathlib import Path


STAGES = ["setup", "state_apply", "current_test_apply", "current_test", "future_gold_apply",
          "future_test_apply", "future_fail_to_pass", "future_pass_to_pass", "current_after_future"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--markdown", required=True, type=Path)
    p.add_argument("--minimum", type=int, default=15)
    args = p.parse_args()
    paths = [Path(x) for pattern in args.inputs for x in glob.glob(pattern)]
    rows = [json.loads(line) for path in paths for line in path.read_text().splitlines() if line.strip()]
    by_key = {row["preflight_key"]: row for row in rows}
    failures = Counter()
    for row in by_key.values():
        if row.get("eligible_state"):
            continue
        if row.get("fatal"):
            failures[row["fatal"]] += 1
            continue
        for stage in STAGES:
            result = row.get(stage)
            if isinstance(result, dict) and result.get("returncode") not in (0, None):
                failures[stage] += 1
                break
        else:
            failures["unclassified"] += 1
    eligible = sorted(row["pair_id"] for row in by_key.values() if row.get("eligible_state"))
    output = {
        "status": "GO" if len(eligible) >= args.minimum else "NO_GO",
        "protocol_sha256": sha(args.protocol),
        "input_sha256": {str(path): sha(path) for path in paths},
        "unique_rows": len(by_key), "eligible_repositories": len(eligible),
        "minimum_required": args.minimum, "eligible_pair_ids": eligible,
        "first_failure_stage": dict(failures),
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    args.markdown.write_text(
        "# Common-snapshot extension preflight\n\n"
        f"Status: **{output['status']}**. {len(eligible)}/{len(by_key)} repository-disjoint historical "
        f"arms passed every frozen gate; the continuation threshold was {args.minimum}.\n\n"
        "First failed stage: " + ", ".join(f"{key}={value}" for key, value in sorted(failures.items())) +
        ". No candidate-state future outcome was inspected or used for selection.\n"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
