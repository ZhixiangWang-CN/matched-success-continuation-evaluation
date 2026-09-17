#!/usr/bin/env python3
"""Analyze a complete 45-run common-snapshot panel for one frozen consumer."""
from __future__ import annotations

import argparse
import glob
import json
import random
import statistics
from pathlib import Path

from analyze_symmetric_future_repeats import METRICS, edit_lines, percentile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--expected-protocol", required=True)
    parser.add_argument("--sol-analysis", type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=280910)
    args = parser.parse_args()

    rows: list[dict] = []
    for pattern in args.inputs:
        for path in sorted(glob.glob(pattern)):
            rows.extend(json.loads(line) for line in Path(path).read_text().splitlines() if line.strip())

    pair_ids = sorted(json.loads(args.manifest.read_text())["eligible_future_pair_ids"])
    keyed = {(row["pair_id"], row["state_id"], row["repeat_index"]): row for row in rows}
    expected = {(pair, state, repeat) for pair in pair_ids
                for state in ("historical", "s0", "s1") for repeat in (0, 1, 2)}
    if len(keyed) != len(rows):
        raise SystemExit("duplicate pair/state/repeat rows")
    if set(keyed) != expected:
        raise SystemExit(f"incomplete panel: missing={sorted(expected-set(keyed))}, extra={sorted(set(keyed)-expected)}")
    invalid = [key for key, row in keyed.items()
               if row.get("fatal") or row.get("model") != args.expected_model
               or row.get("protocol_id") != args.expected_protocol
               or row.get("future_fail_to_pass") is None
               or row.get("current_fail_to_pass") is None]
    if invalid:
        raise SystemExit(f"invalid or mismatched sessions require identical-key rerun: {invalid}")

    for row in rows:
        row["tool_calls"] = row.get("consumer", {}).get("tool_calls")
        row["edit_lines"] = edit_lines(row)

    by_type: dict[str, dict] = {}
    for state_type in ("historical", "candidate"):
        subset = [row for row in rows if row["state_type"] == state_type]
        by_type[state_type] = {
            "n": len(subset),
            "joint_successes": sum(bool(row["joint_success"]) for row in subset),
            "joint_success_rate": statistics.mean(bool(row["joint_success"]) for row in subset),
            "future_only_success_rate": statistics.mean(bool(row["future_only_success"]) for row in subset),
            "prior_preservation_rate": statistics.mean(bool(row["prior_preserved"]) for row in subset),
            "mean_tool_calls": statistics.mean(row["tool_calls"] for row in subset),
            "mean_seconds": statistics.mean(row["seconds"] for row in subset),
            "mean_edit_lines": statistics.mean(row["edit_lines"] for row in subset),
        }

    pair_effects: dict[str, dict] = {}
    for pair in pair_ids:
        historical = [row for row in rows if row["pair_id"] == pair and row["state_type"] == "historical"]
        candidates = [row for row in rows if row["pair_id"] == pair and row["state_type"] == "candidate"]
        pair_effects[pair] = {}
        for metric in METRICS:
            h = statistics.mean(float(row[metric]) for row in historical)
            c = statistics.mean(float(row[metric]) for row in candidates)
            pair_effects[pair][metric] = {"historical": h, "candidate": c, "difference": c - h}
        pair_effects[pair]["state_success_counts"] = {
            state: sum(bool(keyed[(pair, state, repeat)]["joint_success"]) for repeat in (0, 1, 2))
            for state in ("historical", "s0", "s1")
        }

    rng = random.Random(args.seed)
    aggregate: dict[str, dict] = {}
    for metric in METRICS:
        effects = [pair_effects[pair][metric]["difference"] for pair in pair_ids]
        boot = [statistics.mean(rng.choice(effects) for _ in effects) for _ in range(args.bootstrap)]
        aggregate[metric] = {
            "candidate_minus_historical": statistics.mean(effects),
            "pair_cluster_bootstrap_ci95": [percentile(boot, 0.025), percentile(boot, 0.975)],
        }

    result = {
        "protocol": args.expected_protocol,
        "model": args.expected_model,
        "complete": True,
        "rows": len(rows),
        "pairs": len(pair_ids),
        "repeats_per_state": 3,
        "by_state_type": by_type,
        "pair_effects": pair_effects,
        "aggregate_pair_weighted_effects": aggregate,
        "bootstrap": {"draws": args.bootstrap, "seed": args.seed, "unit": "future_pair"},
    }
    if args.sol_analysis:
        sol = json.loads(args.sol_analysis.read_text())
        result["cross_consumer_descriptive"] = {
            metric: {
                "sol": sol["aggregate_pair_weighted_effects"][metric]["candidate_minus_historical"],
                "terra": aggregate[metric]["candidate_minus_historical"],
                "terra_minus_sol": aggregate[metric]["candidate_minus_historical"]
                - sol["aggregate_pair_weighted_effects"][metric]["candidate_minus_historical"],
            }
            for metric in METRICS
        }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n")
    lines = [f"# Common-snapshot consumer panel: {args.expected_model}", "",
             f"Complete: {len(rows)}/45 valid sessions across {len(pair_ids)} future pairs.", "",
             "| State | Joint success | Future only | Prior preserved | Tools | Seconds | Edit lines |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for state in ("historical", "candidate"):
        value = by_type[state]
        lines.append(f"| {state} | {value['joint_successes']}/{value['n']} ({value['joint_success_rate']:.1%}) | "
                     f"{value['future_only_success_rate']:.1%} | {value['prior_preservation_rate']:.1%} | "
                     f"{value['mean_tool_calls']:.2f} | {value['mean_seconds']:.1f} | {value['mean_edit_lines']:.1f} |")
    lines += ["", "## Pair-weighted candidate minus historical effects", ""]
    for metric in METRICS:
        value = aggregate[metric]
        lines.append(f"- {metric}: {value['candidate_minus_historical']:.4f}; pair-cluster bootstrap 95% CI "
                     f"[{value['pair_cluster_bootstrap_ci95'][0]:.4f}, {value['pair_cluster_bootstrap_ci95'][1]:.4f}]")
    lines += ["", "This is a within-OpenAI-family consumer-sensitivity panel, not a cross-vendor replication."]
    args.output_md.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
