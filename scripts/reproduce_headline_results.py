#!/usr/bin/env python3
"""Validate the paper's headline quantities from frozen result artifacts."""
from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def close(actual: float, expected: float, label: str, tol: float = 1e-10) -> None:
    if not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=tol):
        raise AssertionError(f"{label}: expected {expected}, found {actual}")


def main() -> None:
    audit = load("empirical_results/paper_level_audit.json")
    if not audit["integrity"]["passed"]:
        raise AssertionError("paper-level artifact audit is not marked as passed")
    close(audit["coding_scale_summary"]["clean_continuation_success"], 0.6833333333333333, "coding clean")
    close(audit["coding_scale_summary"]["debt_continuation_success"], 0.4083333333333333, "coding alternative")
    close(audit["enterprise_scale_summary"]["clean_continuation_success"], 0.4125, "enterprise clean")
    close(audit["enterprise_scale_summary"]["debt_continuation_success"], 0.325, "enterprise alternative")

    selection = load("prospective_rsd_v3/continuation_selection_analysis/analysis_yury_official.json")
    if selection["coverage"]["rows"] != 384 or selection["coverage"]["current_preservation"]["true"] != 384:
        raise AssertionError("continuation-selection panel is incomplete")
    close(selection["primary"]["continuation_selected_value"], 0.9166666666666666, "selected value")
    close(selection["primary"]["current_success_random_value"], 0.8169693732193734, "random value")
    close(selection["primary"]["effect"], 0.09969729344729328, "selection effect")

    curve = load("prospective_rsd_v3/recovery_curve_analysis/recovery_curve_cluster_results.json")
    if curve["validation"]["retained_rows_per_consumer"] != 598 or curve["validation"]["retained_arms"] != 46:
        raise AssertionError("recovery-curve retained panel differs from the frozen analysis")
    for consumer, expected in (("codex", 0.5652173913043478), ("claude", 0.43478260869565216)):
        close(curve["primary_strict"][consumer]["budgets"]["10"]["estimate"], expected, f"{consumer} B=10")

    sol = load("prospective_rsd_v3/symmetric_sol_repeats/analysis_45.json")
    terra = load("prospective_rsd_v3/symmetric_terra/analysis_45_terra.json")
    if not sol["complete"] or not terra["complete"] or sol["rows"] != 45 or terra["rows"] != 45:
        raise AssertionError("common-snapshot panels are incomplete")
    close(sol["aggregate_pair_weighted_effects"]["joint_success"]["candidate_minus_historical"], 0.1, "Sol common snapshot")
    close(terra["aggregate_pair_weighted_effects"]["joint_success"]["candidate_minus_historical"], 1 / 30, "Terra common snapshot")

    print("HEADLINE_RESULTS_OK")
    print("controlled_coding=68.33% vs 40.83%")
    print("controlled_enterprise=41.25% vs 32.50%")
    print("frozen_cross_family_selection=91.67% vs 81.70% random (+9.97 pp; gate not met)")
    print("recovery_B10=56.52% Codex, 43.48% Claude (46 arms each)")
    print("common_snapshot=+10.00 pp Sol, +3.33 pp Terra (45 sessions each)")


if __name__ == "__main__":
    main()
