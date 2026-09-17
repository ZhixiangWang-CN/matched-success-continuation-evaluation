#!/usr/bin/env python3
"""Reference-free heterogeneity analysis for natural terminal states.

This analysis deliberately does *not* select the best observed state as a
reference.  It treats a state's estimand as its uniformly weighted mean over
the crossed consumer x future-task cells.  Repeated successor generations for
identical source text are averaged within their cell, so accidentally common
source strings do not receive more weight in the estimand.

Inference uses a randomization null. Within each family x consumer x future
stratum, repeat-averaged cell values are permuted across source states. This
retains consumer/task difficulty and the empirical measurement distribution
without assuming nominal repeated generations are independent. A secondary
binary-slot permutation provides a sensitivity analysis under independence.
The null quantifies how much dispersion is expected from finite evaluation.

The script identifies heterogeneity over this fixed future/consumer bank.  It
does not identify a clean/oracle reference, signed state debt, prevalence in a
deployment population, or generalization to unseen futures or executors.
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr


def load_jsonl(paths: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def finite_float(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def percentile_interval(values: np.ndarray, level: float = 0.95) -> list[float]:
    tail = (1.0 - level) / 2.0
    return [float(np.quantile(values, tail)), float(np.quantile(values, 1.0 - tail))]


def pairwise_abs(values: np.ndarray) -> float:
    if len(values) < 2:
        return float("nan")
    return float(np.mean([abs(a - b) for a, b in itertools.combinations(values, 2)]))


def rank_corr(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return finite_float(float(spearmanr(x, y).statistic))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--producers", nargs="+", required=True)
    parser.add_argument("--successors", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--permutations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260831)
    args = parser.parse_args()

    producer_rows = load_jsonl(args.producers)
    successor_rows = load_jsonl(args.successors)

    # Remove literal reruns of the same intended generation.  Different
    # producer/sample paths that yielded identical source are retained as
    # repeated successor draws and later averaged within their source-state
    # cell.
    successor_by_generation = {
        (
            row["consumer"],
            row["producer"],
            row["family"],
            row["producer_sample"],
            row["source_sha256"],
            row["future_id"],
        ): row
        for row in successor_rows
    }
    successor_rows = list(successor_by_generation.values())

    successful_hashes = {
        (row["family"], row["source_sha256"])
        for row in producer_rows
        if row.get("current_success")
    }
    successor_rows = [
        row
        for row in successor_rows
        if (row["family"], row["source_sha256"]) in successful_hashes
    ]

    families = sorted({row["family"] for row in successor_rows})
    rng = np.random.default_rng(args.seed)
    family_objects: dict[str, dict[str, Any]] = {}

    for family in families:
        rows = [row for row in successor_rows if row["family"] == family]
        states = sorted({row["source_sha256"] for row in rows})
        consumers = sorted({row["consumer"] for row in rows})
        futures = sorted({row["future_id"] for row in rows})
        strata = [(consumer, future) for consumer in consumers for future in futures]

        cell_outcomes: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        for row in rows:
            cell_outcomes[(row["source_sha256"], row["consumer"], row["future_id"])].append(
                int(bool(row["future_success"]))
            )

        missing = [
            (state, consumer, future)
            for state in states
            for consumer, future in strata
            if not cell_outcomes[(state, consumer, future)]
        ]
        if missing:
            raise ValueError(f"{family}: crossed design has {len(missing)} missing cells")

        observed_matrix = np.array(
            [
                [np.mean(cell_outcomes[(state, consumer, future)]) for consumer, future in strata]
                for state in states
            ],
            dtype=float,
        )
        observed_scores = observed_matrix.mean(axis=1)
        observed_variance = float(np.var(observed_scores, ddof=1))
        observed_pairwise = pairwise_abs(observed_scores)

        # Each null draw preserves successes within every consumer x future
        # stratum, shuffles them across the existing state slots, then uses the
        # same cell-mean and uniform-cell aggregation as the observed statistic.
        # Primary null: permute repeat-averaged cell values. This treats each
        # state x consumer x future cell as an observational unit and does not
        # assume that nominal repeats of the same prompt are independent.
        null_variances = np.empty(args.permutations, dtype=float)
        null_pairwise = np.empty(args.permutations, dtype=float)
        # Sensitivity null: shuffle individual binary generation slots. This
        # can exploit repeated draws, but requires conditional independence.
        slot_null_variances = np.empty(args.permutations, dtype=float)
        slot_null_pairwise = np.empty(args.permutations, dtype=float)
        counts_by_stratum: list[list[int]] = []
        outcomes_by_stratum: list[np.ndarray] = []
        for consumer, future in strata:
            counts = [len(cell_outcomes[(state, consumer, future)]) for state in states]
            outcomes = np.array(
                [
                    outcome
                    for state in states
                    for outcome in cell_outcomes[(state, consumer, future)]
                ],
                dtype=float,
            )
            counts_by_stratum.append(counts)
            outcomes_by_stratum.append(outcomes)

        for permutation in range(args.permutations):
            cell_null_matrix = np.column_stack(
                [rng.permutation(observed_matrix[:, column]) for column in range(observed_matrix.shape[1])]
            )
            cell_null_scores = cell_null_matrix.mean(axis=1)
            null_variances[permutation] = np.var(cell_null_scores, ddof=1)
            null_pairwise[permutation] = pairwise_abs(cell_null_scores)

            null_matrix = np.empty_like(observed_matrix)
            for column, (counts, outcomes) in enumerate(zip(counts_by_stratum, outcomes_by_stratum)):
                shuffled = rng.permutation(outcomes)
                offset = 0
                for state_index, count in enumerate(counts):
                    null_matrix[state_index, column] = shuffled[offset : offset + count].mean()
                    offset += count
            null_scores = null_matrix.mean(axis=1)
            slot_null_variances[permutation] = np.var(null_scores, ddof=1)
            slot_null_pairwise[permutation] = pairwise_abs(null_scores)

        # Descriptive stability across disjoint halves of the four future-task
        # bank.  We enumerate the three unique 2-vs-2 partitions.
        future_splits: list[dict[str, Any]] = []
        if len(futures) == 4:
            for left_indices in [(0, 1), (0, 2), (0, 3)]:
                left = [futures[index] for index in left_indices]
                right = [future for future in futures if future not in left]
                left_columns = [index for index, (_, future) in enumerate(strata) if future in left]
                right_columns = [index for index, (_, future) in enumerate(strata) if future in right]
                left_scores = observed_matrix[:, left_columns].mean(axis=1).tolist()
                right_scores = observed_matrix[:, right_columns].mean(axis=1).tolist()
                future_splits.append(
                    {
                        "left": left,
                        "right": right,
                        "spearman": rank_corr(left_scores, right_scores),
                    }
                )

        consumer_agreement: list[dict[str, Any]] = []
        for consumer_a, consumer_b in itertools.combinations(consumers, 2):
            columns_a = [index for index, (consumer, _) in enumerate(strata) if consumer == consumer_a]
            columns_b = [index for index, (consumer, _) in enumerate(strata) if consumer == consumer_b]
            scores_a = observed_matrix[:, columns_a].mean(axis=1).tolist()
            scores_b = observed_matrix[:, columns_b].mean(axis=1).tolist()
            consumer_agreement.append(
                {
                    "consumer_a": consumer_a,
                    "consumer_b": consumer_b,
                    "spearman": rank_corr(scores_a, scores_b),
                }
            )

        family_objects[family] = {
            "states": states,
            "n_states": len(states),
            "consumers": consumers,
            "futures": futures,
            "strata": strata,
            "observed_scores": observed_scores,
            "observed_variance": observed_variance,
            "observed_pairwise": observed_pairwise,
            "null_variances": null_variances,
            "null_pairwise": null_pairwise,
            "slot_null_variances": slot_null_variances,
            "slot_null_pairwise": slot_null_pairwise,
            "observed_matrix": observed_matrix,
            "cell_outcomes": cell_outcomes,
            "future_splits": future_splits,
            "consumer_agreement": consumer_agreement,
        }

    # Pooled within-family variance.  The (n-1) weights correspond to the sum
    # of within-family squares, avoiding artificial dispersion from different
    # family difficulty levels.
    denominator = sum(obj["n_states"] - 1 for obj in family_objects.values())
    global_observed_variance = sum(
        (obj["n_states"] - 1) * obj["observed_variance"] for obj in family_objects.values()
    ) / denominator
    global_null_variances = sum(
        (obj["n_states"] - 1) * obj["null_variances"] for obj in family_objects.values()
    ) / denominator
    global_observed_pairwise = sum(
        obj["n_states"] * obj["observed_pairwise"] for obj in family_objects.values()
    ) / sum(obj["n_states"] for obj in family_objects.values())
    global_null_pairwise = sum(
        obj["n_states"] * obj["null_pairwise"] for obj in family_objects.values()
    ) / sum(obj["n_states"] for obj in family_objects.values())
    global_slot_null_variances = sum(
        (obj["n_states"] - 1) * obj["slot_null_variances"] for obj in family_objects.values()
    ) / denominator
    global_slot_null_pairwise = sum(
        obj["n_states"] * obj["slot_null_pairwise"] for obj in family_objects.values()
    ) / sum(obj["n_states"] for obj in family_objects.values())

    def summarize_stat(observed: float, null: np.ndarray) -> dict[str, Any]:
        null_mean = float(np.mean(null))
        return {
            "observed": observed,
            "null_mean": null_mean,
            "null_95_interval": percentile_interval(null),
            "noise_corrected_observed_minus_null_mean": observed - null_mean,
            "noise_corrected_truncated_at_zero": max(0.0, observed - null_mean),
            "randomization_p_upper_tail": float((1 + np.sum(null >= observed)) / (len(null) + 1)),
        }

    family_results: dict[str, Any] = {}
    for family, obj in family_objects.items():
        split_values = [item["spearman"] for item in obj["future_splits"] if item["spearman"] is not None]
        consumer_values = [
            item["spearman"] for item in obj["consumer_agreement"] if item["spearman"] is not None
        ]
        replicate_counts = [
            len(obj["cell_outcomes"][(state, consumer, future)])
            for state in obj["states"]
            for consumer, future in obj["strata"]
        ]
        family_results[family] = {
            "n_states": obj["n_states"],
            "n_consumers": len(obj["consumers"]),
            "n_futures": len(obj["futures"]),
            "n_crossed_cells_per_state": len(obj["strata"]),
            "successor_draws_per_cell": {
                "min": int(min(replicate_counts)),
                "median": float(np.median(replicate_counts)),
                "max": int(max(replicate_counts)),
            },
            "state_value_descriptive": {
                "mean": float(np.mean(obj["observed_scores"])),
                "sd": float(np.std(obj["observed_scores"], ddof=1)),
                "min": float(np.min(obj["observed_scores"])),
                "max": float(np.max(obj["observed_scores"])),
                "distinct_values": len(set(obj["observed_scores"].tolist())),
            },
            "between_state_variance": summarize_stat(
                obj["observed_variance"], obj["null_variances"]
            ),
            "mean_pairwise_absolute_gap": summarize_stat(
                obj["observed_pairwise"], obj["null_pairwise"]
            ),
            "independent_binary_slot_sensitivity": {
                "between_state_variance": summarize_stat(
                    obj["observed_variance"], obj["slot_null_variances"]
                ),
                "mean_pairwise_absolute_gap": summarize_stat(
                    obj["observed_pairwise"], obj["slot_null_pairwise"]
                ),
            },
            "future_split_rank_reliability": {
                "partitions": obj["future_splits"],
                "median_spearman": finite_float(float(np.median(split_values))) if split_values else None,
            },
            "cross_consumer_rank_reliability": {
                "pairs": obj["consumer_agreement"],
                "median_spearman": finite_float(float(np.median(consumer_values)))
                if consumer_values
                else None,
            },
            "states": [
                {"source_sha256": state, "uniform_crossed_value": float(score)}
                for state, score in zip(obj["states"], obj["observed_scores"])
            ],
        }

    # Family-wise Holm correction, separately for the two exploratory
    # heterogeneity statistics. The global test remains the primary test.
    for statistic_name in ["between_state_variance", "mean_pairwise_absolute_gap"]:
        ordered = sorted(
            family_results,
            key=lambda family: family_results[family][statistic_name]["randomization_p_upper_tail"],
        )
        running = 0.0
        m = len(ordered)
        for rank, family in enumerate(ordered):
            raw = family_results[family][statistic_name]["randomization_p_upper_tail"]
            running = max(running, min(1.0, (m - rank) * raw))
            family_results[family][statistic_name]["holm_adjusted_p"] = running

    result = {
        "analysis": "reference-free crossed randomization analysis of natural terminal states",
        "seed": args.seed,
        "permutations": args.permutations,
        "data_accounting": {
            "producer_attempts": len(producer_rows),
            "successful_producer_attempts": sum(bool(row.get("current_success")) for row in producer_rows),
            "literal_successor_generations_after_deduplication": len(successor_rows),
            "unique_successful_source_states_evaluated": sum(
                obj["n_states"] for obj in family_objects.values()
            ),
            "families": len(family_objects),
        },
        "estimand": (
            "For each source state, the uniform mean successor success over the fixed "
            "consumer x future-task bank; repeated generations of an identical source "
            "within a cell are averaged before cells are uniformly weighted."
        ),
        "null": (
            "Within each family x consumer x future stratum, repeat-averaged state-cell "
            "values are exchangeable across source states. A secondary sensitivity analysis "
            "instead shuffles binary generation slots and assumes within-cell repeats are independent."
        ),
        "global": {
            "pooled_within_family_between_state_variance": summarize_stat(
                global_observed_variance, global_null_variances
            ),
            "state_count_weighted_mean_pairwise_absolute_gap": summarize_stat(
                global_observed_pairwise, global_null_pairwise
            ),
            "independent_binary_slot_sensitivity": {
                "pooled_within_family_between_state_variance": summarize_stat(
                    global_observed_variance, global_slot_null_variances
                ),
                "state_count_weighted_mean_pairwise_absolute_gap": summarize_stat(
                    global_observed_pairwise, global_slot_null_pairwise
                ),
            },
        },
        "families": family_results,
        "identifies": [
            "Whether observed source-state continuation values are more dispersed than expected from finite binary successor outcomes under the stated exchangeability null.",
            "A noise-calibrated, reference-free magnitude of dispersion over the fixed evaluated future-task and consumer bank.",
            "Descriptive rank stability across disjoint future halves and across consumers.",
        ],
        "does_not_identify": [
            "A clean or oracle state, or signed residual-state debt for any individual state.",
            "The prevalence or expected magnitude of debt in a deployment population; producer attempts and task families were selected.",
            "Continuation value under unseen future-task distributions or unseen executors.",
            "A causal effect of naturally generated state structure; state content is observational and may be confounded with producer and generation seed.",
            "Reliable state rankings when split-half or cross-consumer agreement is weak.",
        ],
    }

    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    global_variance = result["global"]["pooled_within_family_between_state_variance"]
    global_pairwise = result["global"]["state_count_weighted_mean_pairwise_absolute_gap"]
    slot_sensitivity = result["global"]["independent_binary_slot_sensitivity"]
    lines = [
        "# Reference-Free Natural-State Heterogeneity Analysis",
        "",
        "## Design",
        "",
        result["estimand"],
        "",
        "The best observed state is never used as a reference. " + result["null"],
        "",
        "## Global result",
        "",
        f"- Pooled within-family observed state-value variance: {global_variance['observed']:.6f}.",
        f"- Randomization-null mean variance: {global_variance['null_mean']:.6f} "
        f"(95% interval {global_variance['null_95_interval'][0]:.6f}--{global_variance['null_95_interval'][1]:.6f}).",
        f"- Noise-corrected excess variance: {global_variance['noise_corrected_observed_minus_null_mean']:.6f}; "
        f"upper-tail randomization p={global_variance['randomization_p_upper_tail']:.6g}.",
        f"- Observed mean pairwise absolute gap: {global_pairwise['observed']:.4f}; "
        f"null mean {global_pairwise['null_mean']:.4f}; corrected gap "
        f"{global_pairwise['noise_corrected_observed_minus_null_mean']:.4f}; "
        f"p={global_pairwise['randomization_p_upper_tail']:.6g}.",
        f"- Binary-slot sensitivity (requires independent repeats): corrected variance "
        f"{slot_sensitivity['pooled_within_family_between_state_variance']['noise_corrected_observed_minus_null_mean']:.6f}, "
        f"p={slot_sensitivity['pooled_within_family_between_state_variance']['randomization_p_upper_tail']:.6g}; "
        f"corrected pairwise gap {slot_sensitivity['state_count_weighted_mean_pairwise_absolute_gap']['noise_corrected_observed_minus_null_mean']:.4f}, "
        f"p={slot_sensitivity['state_count_weighted_mean_pairwise_absolute_gap']['randomization_p_upper_tail']:.6g}.",
        "",
        "## Family-level results",
        "",
        "| Family | States | Obs. variance | Null variance | Corrected | p | Holm p | Obs. pairwise gap | Corrected gap | p | Holm p | Future-split rho | Consumer rho |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family, family_result in family_results.items():
        variance = family_result["between_state_variance"]
        pairwise = family_result["mean_pairwise_absolute_gap"]
        split_rho = family_result["future_split_rank_reliability"]["median_spearman"]
        consumer_rho = family_result["cross_consumer_rank_reliability"]["median_spearman"]
        lines.append(
            f"| {family} | {family_result['n_states']} | {variance['observed']:.5f} | "
            f"{variance['null_mean']:.5f} | {variance['noise_corrected_observed_minus_null_mean']:.5f} | "
            f"{variance['randomization_p_upper_tail']:.4f} | {variance['holm_adjusted_p']:.4f} | {pairwise['observed']:.3f} | "
            f"{pairwise['noise_corrected_observed_minus_null_mean']:.3f} | "
            f"{pairwise['randomization_p_upper_tail']:.4f} | {pairwise['holm_adjusted_p']:.4f} | "
            f"{split_rho if split_rho is not None else 'NA'} | "
            f"{consumer_rho if consumer_rho is not None else 'NA'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This analysis can support a claim of reference-free heterogeneity only when the "
            "randomization-calibrated dispersion exceeds the null. It cannot turn the observed "
            "family maximum into a clean counterfactual, assign signed debt to states, or estimate "
            "deployment prevalence. Future-split and cross-consumer correlations diagnose whether "
            "a single state ranking is stable; low correlations imply executor/task dependence.",
            "",
            "## What is not identified",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result["does_not_identify"])
    Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
