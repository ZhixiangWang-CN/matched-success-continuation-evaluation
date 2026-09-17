#!/usr/bin/env python3
"""Apply the frozen V3.2 same-producer diversity gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", nargs="+", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = [row for path in args.candidates for row in read_jsonl(path)]
    successful = [row for row in rows if row.get("current_success")]
    unique = {row.get("alternative_delta_hash") for row in successful
              if row.get("alternative_delta_hash")}
    blocks = {}
    for path in args.candidates:
        block_rows = read_jsonl(path)
        blocks[path.stem] = {"rows": len(block_rows),
                             "success": sum(bool(row.get("current_success")) for row in block_rows)}
    complete = len(rows) == 16 and all(value["rows"] == 8 for value in blocks.values())
    criteria = {"success_at_least_4_of_16": len(successful) >= 4,
                "unique_alternative_deltas_at_least_3": len(unique) >= 3,
                "each_seed_block_has_success": all(value["success"] >= 1 for value in blocks.values())}
    report = {"complete": complete, "rows": len(rows), "success": len(successful),
              "unique_alternative_deltas": len(unique), "seed_blocks": blocks,
              "criteria": criteria,
              "decision": "GO" if complete and all(criteria.values())
                          else "NO_GO" if complete else "INCOMPLETE"}
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
