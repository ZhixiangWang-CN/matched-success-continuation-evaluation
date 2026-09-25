#!/usr/bin/env python3
"""Analyze the frozen 18-repository sequential held-out decision panel."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile_interval(draws: np.ndarray) -> list[float]:
    return [float(x) for x in np.quantile(draws, [0.025, 0.975])]


def cluster_bootstrap(values: np.ndarray, rng: np.random.Generator, draws: int) -> np.ndarray:
    n = len(values)
    indices = rng.integers(0, n, size=(draws, n))
    return values[indices].mean(axis=1)


def exact_sign_flip(values: np.ndarray) -> dict:
    nonzero = np.asarray([float(x) for x in values if abs(float(x)) > 1e-12])
    observed = float(values.mean())
    if len(nonzero) == 0:
        return {"nonzero_clusters": 0, "permutations": 1, "p_one_sided": 1.0, "p_two_sided": 1.0}
    sums = np.zeros(1, dtype=float)
    for value in np.abs(nonzero):
        sums = np.concatenate((sums + value, sums - value))
    permuted = sums / len(values)
    tol = 1e-12
    return {
        "nonzero_clusters": int(len(nonzero)),
        "permutations": int(len(permuted)),
        "p_one_sided": float(np.mean(permuted >= observed - tol)),
        "p_two_sided": float(np.mean(np.abs(permuted) >= abs(observed) - tol)),
    }


def fmt_pct(value: float) -> str:
    return f"{100 * value:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", nargs="+", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bootstrap-draws", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=20260913)
    args = parser.parse_args()

    protocol = json.loads(args.protocol.read_text())
    selection = json.loads(args.selection.read_text())["repositories"]
    rows = [row for path in args.results for row in read_jsonl(path)]
    by_key = {row.get("rollout_key"): row for row in rows}
    pair_ids = sorted({pair for item in selection for pair in item["heldout_pair_ids"]})
    expected = {
        f"{pair}|{state}|codex|R{repeat}|sequential"
        for pair in pair_ids for state in ("historical", "s1") for repeat in (0, 1)
    }
    observed = set(by_key)
    invalid_fatals = [row for row in rows if row.get("fatal") not in (None, "sequential_replay_failed")]
    if len(rows) != len(by_key) or observed != expected or invalid_fatals:
        raise SystemExit(json.dumps({
            "rows": len(rows), "unique": len(by_key), "expected": len(expected),
            "missing": sorted(expected - observed), "extra": sorted(observed - expected),
            "invalid_operational_failures": len(invalid_fatals),
        }, indent=2))
    if any(row.get("evaluation_split") != "sequential_heldout" for row in rows):
        raise SystemExit("non-heldout row found in frozen heldout results")

    row_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        row_groups[(row["anchor_id"], row["state_id"])].append(row)
    ledger = {item["anchor_id"]: item for item in selection}
    repo_rows = []
    for anchor_id, item in sorted(ledger.items()):
        historical = row_groups[(anchor_id, "historical")]
        candidate = row_groups[(anchor_id, "s1")]
        if len(historical) != 4 or len(candidate) != 4:
            raise SystemExit(f"expected four rows per state for {anchor_id}")
        h = float(np.mean([bool(row.get("strict_joint_success")) for row in historical]))
        c = float(np.mean([bool(row.get("strict_joint_success")) for row in candidate]))
        selected_state = item["selected_state_id"]
        shortest_state = item["shortest_state_id"]
        selected = h if selected_state == "historical" else c
        shortest = h if shortest_state == "historical" else c
        uniform = 0.5 * (h + c)
        repo_rows.append({
            "repo": item["repo"], "anchor_id": anchor_id,
            "selected_state": selected_state, "shortest_state": shortest_state,
            "historical_success": h, "candidate_success": c,
            "uniform_success": uniform, "shortest_success": shortest,
            "selected_success": selected,
            "selected_minus_uniform": selected - uniform,
            "selected_minus_shortest": selected - shortest,
            "selected_minus_historical": selected - h,
            "candidate_replay_failures": sum(
                row.get("fatal") == "sequential_replay_failed" for row in candidate
            ),
        })

    rng = np.random.default_rng(args.seed)
    policy_fields = {
        "candidate": "candidate_success", "uniform_current_success": "uniform_success",
        "shortest_patch": "shortest_success", "continuation_selected": "selected_success",
        "historical_default": "historical_success",
    }
    policies = {}
    for name, field in policy_fields.items():
        values = np.asarray([row[field] for row in repo_rows], dtype=float)
        boot = cluster_bootstrap(values, rng, args.bootstrap_draws)
        policies[name] = {
            "mean": float(values.mean()), "ci95_repository_bootstrap": percentile_interval(boot),
        }

    effects = {}
    for name, field in {
        "selected_minus_uniform": "selected_minus_uniform",
        "selected_minus_shortest": "selected_minus_shortest",
        "selected_minus_historical": "selected_minus_historical",
    }.items():
        values = np.asarray([row[field] for row in repo_rows], dtype=float)
        boot = cluster_bootstrap(values, rng, args.bootstrap_draws)
        effects[name] = {
            "mean": float(values.mean()), "ci95_repository_bootstrap": percentile_interval(boot),
            "exact_repository_sign_flip": exact_sign_flip(values),
            "positive_repositories": int(np.sum(values > 1e-12)),
            "negative_repositories": int(np.sum(values < -1e-12)),
            "tie_repositories": int(np.sum(np.abs(values) <= 1e-12)),
        }

    historical_rows = [row for row in rows if row["state_id"] == "historical"]
    candidate_rows = [row for row in rows if row["state_id"] == "s1"]
    integrity = {
        "expected_rows": int(protocol["expected_rows"]), "rows": len(rows),
        "unique_rollout_keys": len(by_key), "repositories": len(repo_rows), "future_pairs": len(pair_ids),
        "setup_failures": sum(bool(row.get("setup", {}).get("returncode")) for row in rows),
        "operational_failures": len(invalid_fatals),
        "scientific_sequential_replay_failures": sum(
            row.get("fatal") == "sequential_replay_failed" for row in rows
        ),
        "historical_hidden_test_apply": sum(
            row.get("hidden_test_apply", {}).get("returncode") == 0 for row in historical_rows
        ),
        "candidate_replay_success": sum(bool(row.get("replay_success")) for row in candidate_rows),
        "candidate_hidden_test_apply": sum(
            row.get("hidden_test_apply", {}).get("returncode") == 0 for row in candidate_rows
        ),
        "selected_state_counts": dict(Counter(item["selected_state_id"] for item in selection)),
        "input_sha256": {str(path): sha256(path) for path in args.results},
    }
    output = {
        "status": "COMPLETE_FROZEN_HELDOUT_ANALYSIS",
        "estimand": protocol["primary"],
        "inference_unit": "repository",
        "bootstrap": {"draws": args.bootstrap_draws, "seed": args.seed, "method": "repository-cluster percentile"},
        "integrity": integrity, "policies": policies, "effects": effects,
        "limitations": (
            "Prospective for the frozen 18-repository panel, not a repository-population prevalence estimate. "
            "Historical states are structurally advantaged because observed history was authored on them."
        ),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "sequential_selection_results.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    with (args.output_dir / "sequential_selection_repo_values.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(repo_rows[0]))
        writer.writeheader(); writer.writerows(repo_rows)

    primary = effects["selected_minus_uniform"]
    shortest = effects["selected_minus_shortest"]
    historical = effects["selected_minus_historical"]
    macros = {
        "SeqSelRows": str(len(rows)), "SeqSelRepos": str(len(repo_rows)), "SeqSelFutures": str(len(pair_ids)),
        "SeqSelSelected": fmt_pct(policies["continuation_selected"]["mean"]) + r"\%",
        "SeqSelUniform": fmt_pct(policies["uniform_current_success"]["mean"]) + r"\%",
        "SeqSelShortest": fmt_pct(policies["shortest_patch"]["mean"]) + r"\%",
        "SeqSelHistorical": fmt_pct(policies["historical_default"]["mean"]) + r"\%",
        "SeqSelCandidate": fmt_pct(policies["candidate"]["mean"]) + r"\%",
        "SeqSelEffect": fmt_pct(primary["mean"]),
        "SeqSelEffectLo": fmt_pct(primary["ci95_repository_bootstrap"][0]),
        "SeqSelEffectHi": fmt_pct(primary["ci95_repository_bootstrap"][1]),
        "SeqSelP": f"{primary['exact_repository_sign_flip']['p_one_sided']:.4f}",
        "SeqSelShortestEffect": fmt_pct(shortest["mean"]),
        "SeqSelShortestLo": fmt_pct(shortest["ci95_repository_bootstrap"][0]),
        "SeqSelShortestHi": fmt_pct(shortest["ci95_repository_bootstrap"][1]),
        "SeqSelShortestP": f"{shortest['exact_repository_sign_flip']['p_two_sided']:.4f}",
        "SeqSelHistoricalEffect": fmt_pct(historical["mean"]),
        "SeqSelReplayFailures": str(integrity["scientific_sequential_replay_failures"]),
        "SeqSelCandidateReplay": str(integrity["candidate_replay_success"]),
    }
    tex = ["% Auto-generated by analyze_sequential_decision_heldout_v1c.py"]
    tex += [rf"\newcommand{{\{key}}}{{{value}}}" for key, value in macros.items()]
    (args.output_dir / "sequential_selection_numbers.tex").write_text("\n".join(tex) + "\n")

    table = [
        r"\begin{tabular}{@{}lrrr@{}}", r"\toprule",
        r"Policy & Heldout success & 95\% repo CI & Difference from selected \\", r"\midrule",
    ]
    labels = {
        "continuation_selected": "Continuation selected", "uniform_current_success": "Uniform success tie-break",
        "shortest_patch": "Shortest patch", "historical_default": "Historical default", "candidate": "Agent candidate",
    }
    selected_mean = policies["continuation_selected"]["mean"]
    for key in ("continuation_selected", "uniform_current_success", "shortest_patch", "historical_default", "candidate"):
        stat = policies[key]
        lo, hi = stat["ci95_repository_bootstrap"]
        diff = stat["mean"] - selected_mean
        table.append(f"{labels[key]} & {fmt_pct(stat['mean'])}\\% & [{fmt_pct(lo)}, {fmt_pct(hi)}] & {100*diff:+.2f} pp \\\\")
    table += [r"\bottomrule", r"\end{tabular}"]
    (args.output_dir / "sequential_selection_table.tex").write_text("\n".join(table) + "\n")
    print(json.dumps({"integrity": integrity, "policies": policies, "effects": effects}, indent=2))


if __name__ == "__main__":
    main()
