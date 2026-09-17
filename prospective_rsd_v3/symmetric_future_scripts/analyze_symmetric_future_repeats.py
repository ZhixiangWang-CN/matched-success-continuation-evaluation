#!/usr/bin/env python3
"""Frozen aggregation for protocol 27 common-snapshot repeat panel."""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
from pathlib import Path


METRICS = ("joint_success", "future_only_success", "prior_preserved",
           "tool_calls", "seconds", "edit_lines")


def read_many(patterns: list[str]) -> list[dict]:
    rows = []
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            rows.extend(json.loads(line) for line in Path(path).read_text().splitlines() if line.strip())
    return rows


def edit_lines(row: dict) -> int:
    total = 0
    for line in row.get("agent_diff", {}).get("output", "").splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            total += int(fields[0]) + int(fields[1])
    return total


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int(q * len(values))))]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", nargs="+", required=True)
    p.add_argument("--repeats", nargs="+", required=True)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--output-json", required=True, type=Path)
    p.add_argument("--output-md", required=True, type=Path)
    p.add_argument("--bootstrap", type=int, default=20000)
    p.add_argument("--seed", type=int, default=270910)
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text())
    pair_ids = sorted(manifest["eligible_future_pair_ids"])
    rows = read_many(args.baseline) + read_many(args.repeats)
    for row in rows:
        row.setdefault("repeat_index", 0)
        row["tool_calls"] = row.get("consumer", {}).get("tool_calls")
        row["edit_lines"] = edit_lines(row)
    keyed = {(r["pair_id"], r["state_id"], r["repeat_index"]): r for r in rows}
    if len(keyed) != len(rows):
        raise SystemExit("duplicate pair/state/repeat rows")
    expected = {(pair, state, repeat) for pair in pair_ids
                for state in ("historical", "s0", "s1") for repeat in (0, 1, 2)}
    missing, extra = sorted(expected - set(keyed)), sorted(set(keyed) - expected)
    if missing or extra:
        raise SystemExit(f"incomplete panel: missing={missing}, extra={extra}")
    invalid = [k for k, r in keyed.items() if r.get("fatal") or
               r.get("future_fail_to_pass") is None or r.get("current_fail_to_pass") is None]
    if invalid:
        raise SystemExit(f"invalid sessions require identical-key rerun: {invalid}")

    by_type = {}
    for state_type in ("historical", "candidate"):
        subset = [r for r in rows if r["state_type"] == state_type]
        by_type[state_type] = {
            "n": len(subset),
            "joint_successes": sum(bool(r["joint_success"]) for r in subset),
            "joint_success_rate": statistics.mean(bool(r["joint_success"]) for r in subset),
            "future_only_success_rate": statistics.mean(bool(r["future_only_success"]) for r in subset),
            "prior_preservation_rate": statistics.mean(bool(r["prior_preserved"]) for r in subset),
            "mean_tool_calls": statistics.mean(r["tool_calls"] for r in subset),
            "mean_seconds": statistics.mean(r["seconds"] for r in subset),
            "mean_edit_lines": statistics.mean(r["edit_lines"] for r in subset),
        }

    pair_effects = {}
    for pair in pair_ids:
        historical = [r for r in rows if r["pair_id"] == pair and r["state_type"] == "historical"]
        candidate = [r for r in rows if r["pair_id"] == pair and r["state_type"] == "candidate"]
        effect = {}
        for metric in METRICS:
            h = statistics.mean(float(r[metric]) for r in historical)
            c = statistics.mean(float(r[metric]) for r in candidate)
            effect[metric] = {"historical": h, "candidate": c, "difference": c - h}
        effect["state_success_counts"] = {
            state: sum(bool(keyed[(pair, state, repeat)]["joint_success"]) for repeat in (0, 1, 2))
            for state in ("historical", "s0", "s1")
        }
        pair_effects[pair] = effect

    rng = random.Random(args.seed)
    aggregate = {}
    for metric in METRICS:
        effects = [pair_effects[pair][metric]["difference"] for pair in pair_ids]
        boot = [statistics.mean(rng.choice(effects) for _ in effects) for _ in range(args.bootstrap)]
        aggregate[metric] = {
            "candidate_minus_historical": statistics.mean(effects),
            "pair_cluster_bootstrap_ci95": [percentile(boot, 0.025), percentile(boot, 0.975)],
        }

    result = {
        "protocol": "symmetric-future-repeat-27",
        "complete": True,
        "rows": len(rows),
        "pairs": len(pair_ids),
        "repeats_per_state": 3,
        "by_state_type": by_type,
        "pair_effects": pair_effects,
        "aggregate_pair_weighted_effects": aggregate,
        "bootstrap": {"draws": args.bootstrap, "seed": args.seed, "unit": "future_pair"},
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n")

    lines = ["# Symmetric future repeat panel", "",
             f"Complete: 45/45 valid sessions across {len(pair_ids)} future pairs.", "",
             "| State | Joint success | Future only | Prior preserved | Tools | Seconds | Edit lines |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for state in ("historical", "candidate"):
        x = by_type[state]
        lines.append(f"| {state} | {x['joint_successes']}/{x['n']} ({x['joint_success_rate']:.1%}) | "
                     f"{x['future_only_success_rate']:.1%} | {x['prior_preservation_rate']:.1%} | "
                     f"{x['mean_tool_calls']:.2f} | {x['mean_seconds']:.1f} | {x['mean_edit_lines']:.1f} |")
    lines += ["", "## Pair-weighted candidate minus historical effects", ""]
    for metric in METRICS:
        x = aggregate[metric]
        lines.append(f"- {metric}: {x['candidate_minus_historical']:.4f}; "
                     f"pair-cluster bootstrap 95% CI [{x['pair_cluster_bootstrap_ci95'][0]:.4f}, "
                     f"{x['pair_cluster_bootstrap_ci95'][1]:.4f}]")
    lines += ["", "This panel measures stochastic stability on the frozen five-pair sample; it does not enlarge repository coverage."]
    args.output_md.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
