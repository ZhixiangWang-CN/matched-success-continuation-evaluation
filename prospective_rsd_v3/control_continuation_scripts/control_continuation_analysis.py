#!/usr/bin/env python3
"""Frozen analysis for historical controls and B=10 downstream continuation."""
from __future__ import annotations

import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve()
REPOSITORY_ROOT = HERE.parents[3]
PACKAGE_ROOT = HERE.parents[1]
IN_ANONYMOUS_PACKAGE = (PACKAGE_ROOT / "control_continuation_results").exists()

if IN_ANONYMOUS_PACKAGE:
    OUT = PACKAGE_ROOT / "control_continuation_results"
    PROTOCOL = PACKAGE_ROOT / "continuation_freeze/recovery_control_continuation_protocol_24.json"
    ARMS = PACKAGE_ROOT / "continuation_freeze/recovery_curve_arms_17.json"
    PARENT_MANIFEST = PACKAGE_ROOT / "recovery_curve_analysis/recovery_curve_data_manifest.json"
    PARENT_FILES = {
        "codex": [
            PACKAGE_ROOT / "recovery_curve_raw/codex_valid_v4_s0.jsonl",
            PACKAGE_ROOT / "recovery_curve_raw/codex_valid_v4_s1.jsonl",
        ],
        "claude": [
            PACKAGE_ROOT / "recovery_curve_raw/claude_valid_v2_s0.jsonl",
            PACKAGE_ROOT / "recovery_curve_raw/claude_valid_v2_s1.jsonl",
        ],
    }
else:
    OUT = REPOSITORY_ROOT / "prospective_rsd_v3/control_continuation_results"
    PROTOCOL = REPOSITORY_ROOT / "prospective_rsd_v3/continuation_freeze/recovery_control_continuation_protocol_24.json"
    ARMS = REPOSITORY_ROOT / "prospective_rsd_v3/continuation_freeze/recovery_curve_arms_17.json"
    PARENT_MANIFEST = REPOSITORY_ROOT / "paper/iclr2027/analysis/recovery_curve_data_manifest.json"
    PARENT_FILES = {
        "codex": [
            REPOSITORY_ROOT / "server_staging/prospective_rsd_v3/recovery_curve/codex_valid_v4_s0.jsonl",
            REPOSITORY_ROOT / "server_staging/prospective_rsd_v3/recovery_curve/codex_valid_v4_s1.jsonl",
        ],
        "claude": [
            REPOSITORY_ROOT / "server_staging/prospective_rsd_v3/recovery_curve/claude_valid_v2_s0.jsonl",
            REPOSITORY_ROOT / "server_staging/prospective_rsd_v3/recovery_curve/claude_valid_v2_s1.jsonl",
        ],
    }

FORMAL = OUT / "paired_formal_856.jsonl"
CODEX_FULL = OUT / "codex_formal_437.jsonl"
MANIFEST = OUT / "formal_results_manifest.json"
SEED = 20260907
BOOTSTRAPS = 100_000
NOVEL = {"alteryx__woodwork-640", "cloudpipe__cloudpickle-57", "python-markdown__markdown-984"}


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


def arm_mean(group: list[dict], key: str) -> float:
    vals = [float(row[key]) for row in group if row.get(key) is not None]
    return mean(vals)


def recovery_cost(row: dict, metric: str) -> float:
    if metric == "recovery_sessions":
        return float(len(row.get("recovery_rounds") or []))
    if metric == "recovery_tool_calls":
        value = row.get("recovery_tool_calls")
        if value is not None:
            return float(value)
        return float(sum((r.get("consumer") or {}).get("tool_calls", 0) for r in row.get("recovery_rounds") or []))
    if metric == "recovery_agent_seconds":
        value = row.get("recovery_agent_seconds")
        if value is not None:
            return float(value)
        return float(sum(r.get("seconds", 0.0) for r in row.get("recovery_rounds") or []))
    raise KeyError(metric)


def stratified_cluster_bootstrap(records: list[dict], value: str, rng: np.random.Generator) -> tuple[float, float]:
    clusters = defaultdict(list)
    for record in records:
        clusters[(record["stratum"], record["anchor_id"])].append(float(record[value]))
    strata = {
        stratum: sorted(anchor for s, anchor in clusters if s == stratum)
        for stratum in ("legacy", "novel")
    }
    estimates = np.empty(BOOTSTRAPS, dtype=float)
    for b in range(BOOTSTRAPS):
        sampled: list[float] = []
        for stratum, anchors in strata.items():
            picks = rng.choice(anchors, size=len(anchors), replace=True)
            for anchor in picks:
                sampled.extend(clusters[(stratum, str(anchor))])
        estimates[b] = np.mean(sampled)
    low, high = np.quantile(estimates, [0.025, 0.975])
    return float(low), float(high)


def exact_sign_flip(records: list[dict], value: str) -> dict:
    by_repo = defaultdict(list)
    for record in records:
        by_repo[record["anchor_id"]].append(float(record[value]))
    anchors = sorted(by_repo)
    numerators = np.array([sum(by_repo[a]) for a in anchors], dtype=float)
    denominator = sum(len(by_repo[a]) for a in anchors)
    observed = float(numerators.sum() / denominator)
    null = []
    for signs in itertools.product((-1.0, 1.0), repeat=len(anchors)):
        null.append(float(np.dot(numerators, signs) / denominator))
    null_array = np.asarray(null)
    eps = 1e-12
    return {
        "n_repository_clusters": len(anchors),
        "observed": observed,
        "two_sided_p": float(np.mean(np.abs(null_array) >= abs(observed) - eps)),
        "one_sided_greater_p": float(np.mean(null_array >= observed - eps)),
        "repository_differences": {a: mean(by_repo[a]) for a in anchors},
    }


def contrast_summary(records: list[dict], value: str, rng: np.random.Generator) -> dict:
    estimate = mean([float(r[value]) for r in records])
    low, high = stratified_cluster_bootstrap(records, value, rng)
    return {
        "n_paired_arms": len(records),
        "estimate": estimate,
        "cluster_bootstrap_ci_low": low,
        "cluster_bootstrap_ci_high": high,
        "exact_repository_sign_flip": exact_sign_flip(records, value),
    }


def validate_inputs() -> tuple[list[dict], list[dict], list[dict], dict[str, dict]]:
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["status"] == "FROZEN_VALIDATED_CLAUDE_428_COMPLETE_CASE_RESULTS"
    assert digest(FORMAL) == manifest["outputs"][FORMAL.name]
    assert digest(CODEX_FULL) == manifest["outputs"][CODEX_FULL.name]
    formal = rows(FORMAL)
    codex_full = rows(CODEX_FULL)
    assert len(formal) == len({r["control_key"] for r in formal}) == 856
    assert len(codex_full) == len({r["control_key"] for r in codex_full}) == 437

    parent_manifest = json.loads(PARENT_MANIFEST.read_text())
    expected_hashes = {Path(x["path"]).name: x["sha256"] for x in parent_manifest["input_files"]}
    parent: list[dict] = []
    for paths in PARENT_FILES.values():
        for path in paths:
            assert digest(path) == expected_hashes[path.name]
            parent.extend(rows(path))
    excluded = set(json.loads(PROTOCOL.read_text())["excluded_future_pair_ids"])
    parent = [r for r in parent if r["future_pair_id"] not in excluded]
    assert len(parent) == 1196

    arms = {a["arm_id"]: a for a in json.loads(ARMS.read_text())["arms"] if a["future_pair_id"] not in excluded}
    assert len(arms) == 46
    return formal, codex_full, parent, arms


def historical_curve_and_excess(
    formal: list[dict], parent: list[dict], arms: dict[str, dict], rng: np.random.Generator,
    agents: tuple[str, ...] = ("codex", "claude"),
) -> tuple[dict, list[dict]]:
    results: dict = {}
    flat: list[dict] = []
    for agent in agents:
        hist_rows = [r for r in formal if r["agent"] == agent and r["state_type"] == "historical"]
        parent_cand_rows = [r for r in parent if r["agent"] == agent]
        endpoint_cand_rows = [r for r in formal if r["agent"] == agent and r["state_type"] == "candidate"]
        agent_result = {}
        for budget in (0, 1, 3, 6, 10):
            # Candidate states were independently rerun in the formal collection
            # at the frozen B=10 endpoint. Use those same-batch rows at B=10;
            # the parent curve supplies only B<10.
            cand_rows = endpoint_cand_rows if budget == 10 else parent_cand_rows
            hist_groups = defaultdict(list)
            cand_groups = defaultdict(list)
            for row in hist_rows:
                if row["recovery_budget"] == budget:
                    hist_groups[row["future_pair_id"]].append(row)
            for row in cand_rows:
                if row["recovery_budget"] == budget:
                    cand_groups[row["arm_id"]].append(row)
            hist = {}
            for future_id, group in hist_groups.items():
                hist[future_id] = {
                    "replay_failure": 1.0 - arm_mean(group, "replay_success"),
                    "recovery_sessions": mean([recovery_cost(r, "recovery_sessions") for r in group]),
                    "recovery_tool_calls": mean([recovery_cost(r, "recovery_tool_calls") for r in group]),
                    "recovery_agent_seconds": mean([recovery_cost(r, "recovery_agent_seconds") for r in group]),
                }
            cand = {}
            for arm_id, group in cand_groups.items():
                cand[arm_id] = {
                    "replay_failure": 1.0 - arm_mean(group, "replay_success"),
                    "recovery_sessions": mean([recovery_cost(r, "recovery_sessions") for r in group]),
                    "recovery_tool_calls": mean([recovery_cost(r, "recovery_tool_calls") for r in group]),
                    "recovery_agent_seconds": mean([recovery_cost(r, "recovery_agent_seconds") for r in group]),
                }
            metrics = {}
            for metric in ("replay_failure", "recovery_sessions", "recovery_tool_calls", "recovery_agent_seconds"):
                paired = []
                for arm_id, cvals in cand.items():
                    arm = arms[arm_id]
                    if arm["future_pair_id"] not in hist:
                        continue
                    hval = hist[arm["future_pair_id"]][metric]
                    paired.append({
                        "anchor_id": arm["anchor_id"],
                        "stratum": "novel" if arm["anchor_id"] in NOVEL else "legacy",
                        "difference": cvals[metric] - hval,
                    })
                summary = contrast_summary(paired, "difference", rng)
                summary.update({
                    "historical_mean": mean([v[metric] for v in hist.values()]),
                    "candidate_mean": mean([v[metric] for v in cand.values()]),
                    "direction": "candidate_minus_historical",
                })
                metrics[metric] = summary
                flat.append({"agent": agent, "budget": budget, "metric": metric, **{k: v for k, v in summary.items() if not isinstance(v, dict)}})
            agent_result[str(budget)] = metrics
        results[agent] = agent_result
    return results, flat


def endpoint_arm_values(group: list[dict]) -> dict:
    reached = [r for r in group if r.get("replay_success")]
    available = [r for r in reached if r.get("downstream_verifier_available") is not None]
    certified = [float(bool(r.get("end_to_end_future_certified"))) for r in group]
    joint = [float(bool(r.get("joint_prior_future_certified"))) for r in group]
    conditional = [float(r["downstream_future_success"]) for r in available if r.get("downstream_verifier_available") is True]
    missing = [float(r.get("downstream_verifier_available") is False) for r in available]
    return {
        "replay_success": arm_mean(group, "replay_success"),
        "end_to_end_future_certified": mean(certified),
        "joint_prior_future_certified": mean(joint),
        "downstream_success_conditional": mean(conditional),
        "downstream_verifier_missing_given_replay": mean(missing),
        "conditional_observations": len(conditional),
    }


def downstream_analysis(
    formal: list[dict], arms: dict[str, dict], rng: np.random.Generator,
    agents: tuple[str, ...] = ("codex", "claude"),
) -> tuple[dict, list[dict]]:
    results = {}
    flat = []
    requested = [r for r in formal if r["future_endpoint_requested"]]
    for agent in agents:
        data = [r for r in requested if r["agent"] == agent]
        hist_groups = defaultdict(list)
        cand_groups = defaultdict(list)
        for row in data:
            if row["state_type"] == "historical":
                hist_groups[row["future_pair_id"]].append(row)
            else:
                cand_groups[row["arm_id"]].append(row)
        hist = {key: endpoint_arm_values(group) for key, group in hist_groups.items()}
        cand = {key: endpoint_arm_values(group) for key, group in cand_groups.items()}
        agent_result = {}
        for level in ("pooled", "s0", "s1"):
            selected = [arm_id for arm_id, arm in arms.items() if level == "pooled" or f"|{level}|" in arm_id]
            level_result = {}
            for metric in (
                "replay_success", "end_to_end_future_certified", "joint_prior_future_certified",
                "downstream_success_conditional", "downstream_verifier_missing_given_replay",
            ):
                paired = []
                hvals, cvals = [], []
                for arm_id in selected:
                    arm = arms[arm_id]
                    if arm_id not in cand or arm["future_pair_id"] not in hist:
                        continue
                    hv = hist[arm["future_pair_id"]][metric]
                    cv = cand[arm_id][metric]
                    if np.isnan(hv) or np.isnan(cv):
                        continue
                    # Debt is loss relative to the historical state. For verifier
                    # missingness, positive debt instead means excess candidate missingness.
                    diff = cv - hv if metric == "downstream_verifier_missing_given_replay" else hv - cv
                    paired.append({
                        "anchor_id": arm["anchor_id"],
                        "stratum": "novel" if arm["anchor_id"] in NOVEL else "legacy",
                        "debt": diff,
                    })
                    hvals.append(hv)
                    cvals.append(cv)
                summary = contrast_summary(paired, "debt", rng)
                summary.update({
                    "historical_mean": mean(hvals),
                    "candidate_mean": mean(cvals),
                    "direction": "historical_minus_candidate" if metric != "downstream_verifier_missing_given_replay" else "candidate_minus_historical",
                })
                level_result[metric] = summary
                flat.append({"agent": agent, "level": level, "metric": metric, **{k: v for k, v in summary.items() if not isinstance(v, dict)}})
            agent_result[level] = level_result
        results[agent] = agent_result
    return results, flat


def write_csv(path: Path, records: list[dict]) -> None:
    keys = list(records[0])
    lines = [",".join(keys)]
    for record in records:
        lines.append(",".join(str(record.get(key, "")) for key in keys))
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    formal, codex_full, parent, arms = validate_inputs()
    rng = np.random.default_rng(SEED)
    recovery, recovery_flat = historical_curve_and_excess(formal, parent, arms, rng)
    downstream, downstream_flat = downstream_analysis(formal, arms, rng)
    sensitivity_rng = np.random.default_rng(SEED)
    codex_recovery, codex_recovery_flat = historical_curve_and_excess(
        codex_full, parent, arms, sensitivity_rng, ("codex",))
    codex_downstream, codex_downstream_flat = downstream_analysis(
        codex_full, arms, sensitivity_rng, ("codex",))
    result = {
        "status": "FROZEN_CLAUDE_428_COMPLETE_CASE_ANALYSIS",
        "primary_population": "428 consumer-matched canonical keys per consumer",
        "codex_sensitivity_population": "all 437 Codex keys",
        "analysis_seed": SEED,
        "bootstrap_replicates": BOOTSTRAPS,
        "formal_results_sha256": digest(FORMAL),
        "analysis_script_sha256": digest(Path(__file__)),
        "historical_excess_recovery": recovery,
        "downstream_continuation_debt": downstream,
        "codex_full_437_sensitivity": {
            "historical_excess_recovery": codex_recovery,
            "downstream_continuation_debt": codex_downstream,
        },
    }
    (OUT / "control_continuation_analysis_results.json").write_text(json.dumps(result, indent=2) + "\n")
    write_csv(OUT / "historical_excess_recovery.csv", recovery_flat)
    write_csv(OUT / "downstream_continuation_debt.csv", downstream_flat)
    write_csv(OUT / "codex_full_437_historical_excess_recovery.csv", codex_recovery_flat)
    write_csv(OUT / "codex_full_437_downstream_continuation_debt.csv", codex_downstream_flat)
    print(json.dumps({
        "status": result["status"],
        "recovery_rows": len(recovery_flat),
        "downstream_rows": len(downstream_flat),
    }, indent=2))


if __name__ == "__main__":
    main()
