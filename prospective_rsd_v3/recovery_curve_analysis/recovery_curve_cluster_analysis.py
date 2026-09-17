#!/usr/bin/env python3
"""Frozen recovery-curve analysis with repository-cluster inference.

``verified_recovery`` is a *certifiable-recovery lower bound*: it requires
both replay completion and successful transport and execution of the frozen
prior-task verifier.  ``replay_success`` is the preservation upper bound when
all executed prior verifiers pass, as they do in these frozen rows.  Repeats
are first averaged within state--future arms; inference resamples repositories.
"""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
FREEZE = ROOT / "prospective_rsd_v3" / "continuation_freeze"
RAW = ROOT / "server_staging" / "prospective_rsd_v3" / "recovery_curve"
PROTOCOL_PATH = FREEZE / "recovery_curve_protocol_17.json"
ARMS_PATH = FREEZE / "recovery_curve_arms_17.json"
INPUTS = {
    "claude": [RAW / "claude_valid_v2_s0.jsonl", RAW / "claude_valid_v2_s1.jsonl"],
    "codex": [RAW / "codex_valid_v4_s0.jsonl", RAW / "codex_valid_v4_s1.jsonl"],
}
EXPECTED_PROTOCOL_ID = "409635ca6866dc49501c63f4ff2e310e10f5084ef6362db844b1c755db2fc6a4"
EXPECTED_EXCLUDED_ARMS = {
    "alteryx__woodwork-640|s0|alteryx__woodwork-687",
    "alteryx__woodwork-640|s1|alteryx__woodwork-687",
}
SEED = 20260906
N_BOOT = 100_000
ALPHA = 0.05


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def mean(xs: Iterable[float]) -> float:
    ys = list(xs)
    if not ys:
        raise ValueError("mean of empty sequence")
    return sum(ys) / len(ys)


def percentile(sorted_x: list[float], q: float) -> float:
    if not sorted_x:
        raise ValueError("percentile of empty sequence")
    pos = (len(sorted_x) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return sorted_x[lo]
    return sorted_x[lo] * (hi - pos) + sorted_x[hi] * (pos - lo)


def exact_sign_flip(diffs: list[float], weights: list[int]) -> dict[str, Any]:
    """Exact paired randomization test over repository-level differences."""
    assert len(diffs) == len(weights)
    total_weight = sum(weights)
    observed = sum(d * w for d, w in zip(diffs, weights)) / total_weight
    null = [sum(s * d * w for s, d, w in zip(signs, diffs, weights)) / total_weight
            for signs in itertools.product((-1.0, 1.0), repeat=len(diffs))]
    tol = 1e-12
    return {
        "n_repository_clusters": len(diffs),
        "repository_arm_weights": weights,
        "observed_mean_difference": observed,
        "two_sided_p": sum(abs(x) >= abs(observed) - tol for x in null) / len(null),
        "one_sided_greater_p": sum(x >= observed - tol for x in null) / len(null),
        "positive_repositories": sum(d > tol for d in diffs),
        "negative_repositories": sum(d < -tol for d in diffs),
        "tied_repositories": sum(abs(d) <= tol for d in diffs),
        "repository_differences": diffs,
    }


def stratified_repo_bootstrap(
    repo_values: dict[str, dict[int, float]],
    repo_arm_counts: dict[str, int],
    repo_strata: dict[str, str],
    budgets: list[int],
    rng: random.Random,
) -> list[dict[int, float]]:
    strata: dict[str, list[str]] = defaultdict(list)
    for repo in sorted(repo_values):
        strata[repo_strata[repo]].append(repo)
    draws: list[dict[int, float]] = []
    for _ in range(N_BOOT):
        selected: list[str] = []
        for repos in strata.values():
            selected.extend(rng.choice(repos) for _ in repos)
        draws.append({
            b: sum(repo_values[r][b] * repo_arm_counts[r] for r in selected)
            / sum(repo_arm_counts[r] for r in selected)
            for b in budgets
        })
    return draws


def bootstrap_summary(
    point: dict[int, float], draws: list[dict[int, float]], budgets: list[int]
) -> dict[int, dict[str, float]]:
    # Unstudentized maximum-deviation band across all five frozen budgets.
    max_dev = sorted(max(abs(d[b] - point[b]) for b in budgets) for d in draws)
    critical = percentile(max_dev, 1 - ALPHA)
    out: dict[int, dict[str, float]] = {}
    for b in budgets:
        vals = sorted(d[b] for d in draws)
        out[b] = {
            "estimate": point[b],
            "pointwise_ci_low": percentile(vals, ALPHA / 2),
            "pointwise_ci_high": percentile(vals, 1 - ALPHA / 2),
            "simultaneous_band_low": max(0.0, point[b] - critical),
            "simultaneous_band_high": min(1.0, point[b] + critical),
        }
    return out


def main() -> None:
    protocol = json.loads(PROTOCOL_PATH.read_text())
    arms_doc = json.loads(ARMS_PATH.read_text())
    assert protocol["protocol_id"] == EXPECTED_PROTOCOL_ID
    assert arms_doc["protocol_id"] == EXPECTED_PROTOCOL_ID
    budgets = protocol["budgets"]
    assert budgets == [0, 1, 3, 6, 10]
    arm_meta = {a["arm_id"]: a for a in arms_doc["arms"]}
    assert len(arm_meta) == arms_doc["arm_count"] == 48

    rows_by_consumer: dict[str, list[dict[str, Any]]] = {}
    input_manifest: dict[str, Any] = {}
    all_keys: set[str] = set()
    exclusions: dict[str, Any] = {}
    for consumer, paths in INPUTS.items():
        raw_rows = [r for path in paths for r in load_jsonl(path)]
        assert len(raw_rows) == 624
        assert all(r["protocol_id"] == EXPECTED_PROTOCOL_ID for r in raw_rows)
        keys = [r["curve_key"] for r in raw_rows]
        assert len(keys) == len(set(keys)), f"duplicate curve_key within {consumer}"
        assert not (all_keys & set(keys)), "curve_key collision across consumers"
        all_keys.update(keys)
        bad = [r for r in raw_rows if r.get("fatal") == "replay_worktree_failed"]
        bad_arms = {r["arm_id"] for r in bad}
        assert len(bad) == 26 and bad_arms == EXPECTED_EXCLUDED_ARMS
        assert all(r["arm_id"] in arm_meta for r in raw_rows)
        assert all(r["agent"] == consumer for r in raw_rows)
        rows = [r for r in raw_rows if r.get("fatal") != "replay_worktree_failed"]
        assert len(rows) == 598
        rows_by_consumer[consumer] = rows
        exclusions[consumer] = {
            "reason": "replay_worktree_failed: frozen Git reference absent from container image",
            "rows": len(bad),
            "arms": sorted(bad_arms),
        }
        input_manifest[consumer] = [
            {"path": str(p.relative_to(ROOT)), "sha256": sha256(p), "rows": len(load_jsonl(p))}
            for p in paths
        ]

    retained_arms = set(arm_meta) - EXPECTED_EXCLUDED_ARMS
    assert len(retained_arms) == 46
    expected_repeats = {0: 1, 1: 3, 3: 3, 6: 3, 10: 3}
    for consumer, rows in rows_by_consumer.items():
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            grouped[(r["arm_id"], r["recovery_budget"])].append(r)
        assert set(a for a, _ in grouped) == retained_arms
        for arm in retained_arms:
            for b in budgets:
                rr = grouped[(arm, b)]
                assert len(rr) == expected_repeats[b], (consumer, arm, b, len(rr))
                assert {x["independent_repeat"] for x in rr} == set(range(expected_repeats[b]))

    # Endpoints: `strict` is certifiable recovery, not observed behavioral
    # failure when the old verifier cannot be transported. `nominal` is replay
    # completion and hence the preservation upper bound in this data because
    # every prior verifier that actually ran passed.
    endpoints = {"strict": "verified_recovery", "nominal": "replay_success"}
    arm_means: dict[str, dict[str, dict[int, dict[str, float]]]] = {}
    repo_means: dict[str, dict[str, dict[str, dict[int, float]]]] = {}
    repo_strata: dict[str, str] = {}
    repo_arm_counts: dict[str, int] = {}
    for consumer, rows in rows_by_consumer.items():
        arm_means[consumer] = {}
        repo_means[consumer] = {}
        for endpoint, field in endpoints.items():
            grouped_values: dict[tuple[str, int], list[float]] = defaultdict(list)
            for r in rows:
                grouped_values[(r["arm_id"], r["recovery_budget"])].append(float(bool(r.get(field))))
            arm_means[consumer][endpoint] = {
                arm: {b: mean(grouped_values[(arm, b)]) for b in budgets}
                for arm in sorted(retained_arms)
            }
            by_repo: dict[str, list[str]] = defaultdict(list)
            for arm in retained_arms:
                meta = arm_meta[arm]
                by_repo[meta["repo"]].append(arm)
                old = repo_strata.setdefault(meta["repo"], meta["stratum"])
                assert old == meta["stratum"]
            repo_means[consumer][endpoint] = {
                repo: {b: mean(arm_means[consumer][endpoint][a][b] for a in repo_arms)
                       for b in budgets}
                for repo, repo_arms in sorted(by_repo.items())
            }
            for repo, repo_arms in by_repo.items():
                old_count = repo_arm_counts.setdefault(repo, len(repo_arms))
                assert old_count == len(repo_arms)
            assert len(repo_means[consumer][endpoint]) == 8

    rng = random.Random(SEED)
    primary: dict[str, Any] = {}
    for consumer in sorted(rows_by_consumer):
        values = repo_means[consumer]["strict"]
        point = {
            b: sum(values[r][b] * repo_arm_counts[r] for r in values) / sum(repo_arm_counts.values())
            for b in budgets
        }
        draws = stratified_repo_bootstrap(values, repo_arm_counts, repo_strata, budgets, rng)
        summary = bootstrap_summary(point, draws, budgets)
        primary[consumer] = {
            "estimand": "fraction of arms after averaging independent repeats within arm",
            "budgets": {str(b): summary[b] for b in budgets},
            "confirmatory_B3_vs_B0": exact_sign_flip(
                [values[r][3] - values[r][0] for r in sorted(values)],
                [repo_arm_counts[r] for r in sorted(values)],
            ),
        }

    # Paired consumer contrasts on exactly matched arms/repeats.
    assert {r["curve_key"].replace("|claude|", "|CONSUMER|") for r in rows_by_consumer["claude"]} == {
        r["curve_key"].replace("|codex|", "|CONSUMER|") for r in rows_by_consumer["codex"]
    }
    consumer_comparison: dict[str, Any] = {}
    for b in budgets:
        diffs = [repo_means["codex"]["strict"][r][b] - repo_means["claude"]["strict"][r][b]
                 for r in sorted(repo_strata)]
        consumer_comparison[str(b)] = exact_sign_flip(
            diffs, [repo_arm_counts[r] for r in sorted(repo_strata)]
        )

    # Sensitivity summaries retain unequal arm/row weights and are descriptive.
    sensitivity: dict[str, Any] = {}
    for consumer, rows in rows_by_consumer.items():
        sensitivity[consumer] = {}
        for endpoint, field in endpoints.items():
            sensitivity[consumer][endpoint] = {}
            for b in budgets:
                arms = arm_means[consumer][endpoint]
                arm_weighted = mean(arms[a][b] for a in arms)
                repo_macro = mean(repo_means[consumer][endpoint][r][b] for r in sorted(repo_strata))
                rr = [r for r in rows if r["recovery_budget"] == b]
                row_successes = sum(bool(r.get(field)) for r in rr)
                sensitivity[consumer][endpoint][str(b)] = {
                    "arm_weighted": arm_weighted,
                    "repository_macro": repo_macro,
                    "row_weighted": row_successes / len(rr),
                    "row_successes": row_successes,
                    "row_total": len(rr),
                }

    verifier_accounting: dict[str, Any] = {}
    for consumer, rows in rows_by_consumer.items():
        verifier_accounting[consumer] = {}
        for b in budgets:
            rr = [r for r in rows if r["recovery_budget"] == b]
            completed = [r for r in rr if bool(r.get("replay_success"))]
            available = [r for r in completed if r.get("recovery_prior_task_test") is not None]
            passed = [r for r in available if r["recovery_prior_task_test"].get("returncode") == 0]
            failed = [r for r in available if r["recovery_prior_task_test"].get("returncode") not in (None, 0)]
            unavailable = [r for r in completed if r.get("recovery_prior_task_test") is None]
            assert len(completed) == len(available) + len(unavailable)
            assert not failed, "an executed prior-task verifier failed; update partial-identification logic"
            verifier_accounting[consumer][str(b)] = {
                "rows": len(rr),
                "replay_completed": len(completed),
                "verifier_available_and_passed": len(passed),
                "verifier_available_and_failed": len(failed),
                "verifier_unavailable_after_replay": len(unavailable),
                "preservation_lower_bound": len(passed) / len(rr),
                "preservation_upper_bound": len(completed) / len(rr),
            }

    # Realized recovery cost over every retained attempt, including failed
    # attempts. The budget unit is the maximum number of recovery sessions;
    # tool calls and elapsed seconds provide comparable realized-cost axes.
    realized_cost: dict[str, Any] = {}
    cost_rows: list[dict[str, Any]] = []
    for consumer, rows in rows_by_consumer.items():
        realized_cost[consumer] = {}
        for b in budgets:
            rr = [r for r in rows if r["recovery_budget"] == b]
            per_row = []
            for r in rr:
                rounds = r.get("recovery_rounds") or []
                per_row.append({
                    "sessions": len(rounds),
                    "tool_calls": sum((x.get("consumer") or {}).get("tool_calls", 0) or 0 for x in rounds),
                    "recovery_seconds": sum(float(x.get("seconds", 0) or 0) for x in rounds),
                })
            summary = {
                "rows": len(per_row),
                "mean_sessions": mean(x["sessions"] for x in per_row),
                "mean_tool_calls": mean(x["tool_calls"] for x in per_row),
                "mean_recovery_seconds": mean(x["recovery_seconds"] for x in per_row),
            }
            realized_cost[consumer][str(b)] = summary
            cost_rows.append({"consumer": consumer, "budget": b, **summary})

    strata_results: dict[str, Any] = {}
    for consumer in sorted(rows_by_consumer):
        strata_results[consumer] = {}
        for stratum in sorted(set(repo_strata.values())):
            repos = [r for r in sorted(repo_strata) if repo_strata[r] == stratum]
            strata_results[consumer][stratum] = {
                "n_repositories": len(repos),
                "budgets": {
                    str(b): sum(repo_means[consumer]["strict"][r][b] * repo_arm_counts[r] for r in repos)
                    / sum(repo_arm_counts[r] for r in repos)
                    for b in budgets
                },
            }

    repo_rows: list[dict[str, Any]] = []
    for consumer in sorted(rows_by_consumer):
        for repo in sorted(repo_strata):
            for b in budgets:
                repo_rows.append({
                    "consumer": consumer,
                    "repository": repo,
                    "stratum": repo_strata[repo],
                    "budget": b,
                    "strict_arm_mean": repo_means[consumer]["strict"][repo][b],
                    "nominal_arm_mean": repo_means[consumer]["nominal"][repo][b],
                })

    results = {
        "analysis_status": "FROZEN_INPUTS_VALIDATED",
        "protocol_id": EXPECTED_PROTOCOL_ID,
        "analysis_seed": SEED,
        "bootstrap_replicates": N_BOOT,
        "protocol_sha256": sha256(PROTOCOL_PATH),
        "arms_sha256": sha256(ARMS_PATH),
        "inputs": input_manifest,
        "validation": {
            "unique_curve_keys": len(all_keys),
            "raw_rows_per_consumer": 624,
            "retained_rows_per_consumer": 598,
            "retained_arms": 46,
            "repository_clusters": 8,
            "expected_repeats": expected_repeats,
            "exclusions": exclusions,
        },
        "primary_strict": primary,
        "endpoint_semantics": {
            "strict": "certifiable recovery: replay completes and the transported prior-task verifier runs and passes",
            "nominal": "procedural replay completion",
            "behavioral_preservation": "partially identified between strict and nominal because every transported verifier that ran passed",
        },
        "verifier_accounting": verifier_accounting,
        "realized_recovery_cost": realized_cost,
        "strata": strata_results,
        "consumer_comparison_codex_minus_claude": consumer_comparison,
        "sensitivity": sensitivity,
        "repository_values": repo_rows,
        "inference_notes": {
            "bootstrap": "Stratified repository-cluster bootstrap, preserving the frozen 5 legacy / 3 unopened repository composition.",
            "simultaneous_band": "95% unstudentized max-absolute-deviation band over B={0,1,3,6,10}.",
            "confirmatory_test": "Exact two-sided and directional sign-flip randomization tests over eight paired repository differences at B=3.",
            "scope": "Repository-cluster inference describes these eight selected repositories; it is not a population prevalence estimate.",
        },
    }
    (OUT / "recovery_curve_cluster_results.json").write_text(json.dumps(results, indent=2) + "\n")

    with (OUT / "recovery_curve_repo_values.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(repo_rows[0]))
        writer.writeheader()
        writer.writerows(repo_rows)

    primary_rows: list[dict[str, Any]] = []
    for consumer in sorted(primary):
        for b in budgets:
            x = primary[consumer]["budgets"][str(b)]
            sens = sensitivity[consumer]
            primary_rows.append({
                "consumer": consumer,
                "budget": b,
                "arm_weighted_certifiable_lower": x["estimate"],
                "pointwise_ci_low": x["pointwise_ci_low"],
                "pointwise_ci_high": x["pointwise_ci_high"],
                "simultaneous_low": x["simultaneous_band_low"],
                "simultaneous_high": x["simultaneous_band_high"],
                "repo_macro_certifiable_lower": sens["strict"][str(b)]["repository_macro"],
                "row_weighted_certifiable_lower": sens["strict"][str(b)]["row_weighted"],
                "row_weighted_procedural_upper": sens["nominal"][str(b)]["row_weighted"],
            })
    with (OUT / "recovery_curve_primary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(primary_rows[0]))
        writer.writeheader()
        writer.writerows(primary_rows)

    with (OUT / "recovery_curve_cost.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(cost_rows[0]))
        writer.writeheader()
        writer.writerows(cost_rows)

    lines = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Consumer & Budget & Certifiable lower bound & Pointwise 95\% CI & Simultaneous 95\% band & Preservation upper bound \\",
        r"\midrule",
    ]
    for row in primary_rows:
        lines.append(
            f"{row['consumer'].title()} & {row['budget']} & {100*row['arm_weighted_certifiable_lower']:.1f} & "
            f"[{100*row['pointwise_ci_low']:.1f}, {100*row['pointwise_ci_high']:.1f}] & "
            f"[{100*row['simultaneous_low']:.1f}, {100*row['simultaneous_high']:.1f}] & "
            f"{100*row['row_weighted_procedural_upper']:.1f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "recovery_curve_primary.tex").write_text("\n".join(lines) + "\n")

    compact = [
        r"\begin{tabular}{@{}rcccc@{}}",
        r"\toprule",
        r"$B$ & Claude certifiable [95\% CI] & Claude empirical upper & Codex certifiable [95\% CI] & Codex empirical upper \\",
        r"\midrule",
    ]
    for b in budgets:
        cells = []
        for consumer in ("claude", "codex"):
            x = primary[consumer]["budgets"][str(b)]
            nominal = sensitivity[consumer]["nominal"][str(b)]["row_weighted"]
            cells.extend([
                f"{100*x['estimate']:.1f} [{100*x['pointwise_ci_low']:.1f}, {100*x['pointwise_ci_high']:.1f}]",
                f"{100*nominal:.1f}",
            ])
        compact.append(f"{b} & " + " & ".join(cells) + r" \\")
    compact += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "recovery_curve_compact.tex").write_text("\n".join(compact) + "\n")

    c0 = primary["claude"]["budgets"]["0"]["estimate"]
    c1 = primary["claude"]["budgets"]["1"]["estimate"]
    c3 = primary["claude"]["budgets"]["3"]["estimate"]
    c10 = primary["claude"]["budgets"]["10"]["estimate"]
    x0 = primary["codex"]["budgets"]["0"]["estimate"]
    x3 = primary["codex"]["budgets"]["3"]["estimate"]
    x10 = primary["codex"]["budgets"]["10"]["estimate"]
    x10_nominal = sensitivity["codex"]["nominal"]["10"]["row_weighted"]
    macros = [
        r"% Generated by recovery_curve_cluster_analysis.py; do not edit.",
        r"\newcommand{\CurveProtocol}{409635ca6866dc49501c63f4ff2e310e10f5084ef6362db844b1c755db2fc6a4}",
        f"\\newcommand{{\\CurveRawRows}}{{{len(rows_by_consumer['claude']) + exclusions['claude']['rows']}}}",
        f"\\newcommand{{\\CurveRows}}{{{len(rows_by_consumer['claude'])}}}",
        f"\\newcommand{{\\CurveArms}}{{{len(retained_arms)}}}",
        f"\\newcommand{{\\CurveRepos}}{{{len(repo_strata)}}}",
        f"\\newcommand{{\\CurveExcludedArms}}{{{len(EXPECTED_EXCLUDED_ARMS)}}}",
        f"\\newcommand{{\\CurveClaudeBZero}}{{{100*c0:.2f}}}",
        f"\\newcommand{{\\CurveClaudeBOne}}{{{100*c1:.2f}}}",
        f"\\newcommand{{\\CurveClaudeBThree}}{{{100*c3:.2f}}}",
        f"\\newcommand{{\\CurveClaudeBTen}}{{{100*c10:.2f}}}",
        f"\\newcommand{{\\CurveCodexBZero}}{{{100*x0:.2f}}}",
        f"\\newcommand{{\\CurveCodexBThree}}{{{100*x3:.2f}}}",
        f"\\newcommand{{\\CurveCodexBTen}}{{{100*x10:.2f}}}",
        f"\\newcommand{{\\CurveCodexNominalBTen}}{{{100*x10_nominal:.2f}}}",
        f"\\newcommand{{\\CurveCodexGapBTen}}{{{100*(x10_nominal-x10):.2f}}}",
        f"\\newcommand{{\\CurveClaudeDeltaBThree}}{{{100*(c3-c0):.2f}}}",
        f"\\newcommand{{\\CurveCodexDeltaBThree}}{{{100*(x3-x0):.2f}}}",
        f"\\newcommand{{\\CurveClaudeP}}{{{primary['claude']['confirmatory_B3_vs_B0']['two_sided_p']:.1f}}}",
        f"\\newcommand{{\\CurveCodexP}}{{{primary['codex']['confirmatory_B3_vs_B0']['two_sided_p']:.1f}}}",
    ]
    (OUT / "recovery_curve_numbers.tex").write_text("\n".join(macros) + "\n")

    def pc(x: float) -> str:
        return f"{100*x:.2f}%"

    memo = [
        "# Repository-cluster recovery-curve analysis",
        "",
        f"Protocol `{EXPECTED_PROTOCOL_ID}` was validated against all four final JSONL files. "
        "Each consumer has 624 unique raw rows. Exactly 26 rows from the same two Woodwork arms were excluded because the frozen Git reference was absent from the container image; the analysis therefore contains 598 rows, 46 complete arms, and eight repositories per consumer.",
        "",
        "## Primary analysis",
        "",
        "The `verified_recovery` field is analyzed as a certifiable-recovery lower bound; `replay_success` is the behavioral-preservation upper bound here because every transported prior-task verifier that actually ran passed. A false `verified_recovery` after completed replay therefore denotes verifier unavailability, not an observed behavioral failure. Independent repeats are averaged within each state--future arm, and the frozen estimand is the fraction of arms. Confidence intervals use 100,000 stratified repository-cluster bootstrap samples (five legacy and three outcome-unopened repositories sampled with replacement within stratum); each draw pools all arms in the sampled clusters and divides by their sampled arm count. Simultaneous bands use the bootstrap maximum absolute deviation across the five frozen budgets. B=3 comparisons use exact sign-flip randomization of whole repository clusters, weighted by their retained arm counts.",
        "",
    ]
    for consumer in ("claude", "codex"):
        vals = primary[consumer]["budgets"]
        memo.append(
            f"- {consumer.title()} certifiable-recovery lower bound: " + ", ".join(
                f"B{b} {pc(vals[str(b)]['estimate'])} "
                f"(pointwise 95% CI {pc(vals[str(b)]['pointwise_ci_low'])}--{pc(vals[str(b)]['pointwise_ci_high'])})"
                for b in budgets
            ) + "."
        )
        test = primary[consumer]["confirmatory_B3_vs_B0"]
        memo.append(
            f"- {consumer.title()} confirmatory B3-B0 arm-fraction difference: {pc(test['observed_mean_difference'])}; "
            f"exact two-sided p={test['two_sided_p']:.4f}, directional p={test['one_sided_greater_p']:.4f} "
            f"({test['positive_repositories']} positive, {test['negative_repositories']} negative, {test['tied_repositories']} ties)."
        )
    paired = consumer_comparison["3"]
    memo += [
        f"- At B3, the paired Codex-minus-Claude certifiability difference is {pc(paired['observed_mean_difference'])}; "
        f"exact two-sided p={paired['two_sided_p']:.4f} ({paired['positive_repositories']} positive, "
        f"{paired['negative_repositories']} negative, and {paired['tied_repositories']} tied repositories).",
        "",
        "## Sensitivity and limitations",
        "",
        "Repository-macro and raw-row summaries are included only as sensitivity analyses; raw rows are not independent. With only eight selected repository clusters, cluster intervals are necessarily wide and the exact tests have coarse resolution. Certifiability improvements are concentrated in Kinto and, for Codex beyond B1, ResearchObject; no broad cross-repository or population-prevalence claim is supported. Across completed replays, verifier transport is unavailable in 33 Claude and 142 Codex rows; among the 254 and 307 rows where it runs, respectively, there are zero test failures. The two structurally unavailable Woodwork arms are excluded symmetrically for both consumers and every budget rather than counted as task failures.",
        "",
        "Realized cost is averaged over every retained row, including failed attempts. A recovery session may contain many tool calls, so the allocated session budget is not a normalized compute budget; `recovery_curve_cost.csv` reports mean sessions, tool calls, and recovery seconds at each budget.",
        "",
        "All generated values are reproducible by running `python3 recovery_curve_cluster_analysis.py` from this directory.",
    ]
    (OUT / "recovery_curve_methods_memo.md").write_text("\n".join(memo) + "\n")

    print(json.dumps({
        "status": "ok",
        "primary": primary,
        "consumer_B3": consumer_comparison["3"],
        "outputs": [
            "recovery_curve_cluster_results.json",
            "recovery_curve_primary.csv",
            "recovery_curve_cost.csv",
            "recovery_curve_repo_values.csv",
            "recovery_curve_primary.tex",
            "recovery_curve_compact.tex",
            "recovery_curve_numbers.tex",
            "recovery_curve_methods_memo.md",
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
