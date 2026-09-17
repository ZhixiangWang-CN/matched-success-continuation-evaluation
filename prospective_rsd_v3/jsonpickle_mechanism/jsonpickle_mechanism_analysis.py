#!/usr/bin/env python3
"""Recompute the Jsonpickle mechanism audit and render its paper figure."""
from __future__ import annotations

import glob
import itertools
import json
from collections import defaultdict
from math import comb
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
PAIR = "jsonpickle__jsonpickle-342__TO__jsonpickle__jsonpickle-455"
ANCHOR = "jsonpickle__jsonpickle-342"
OUT_JSON = ROOT / "prospective_rsd_v3/jsonpickle_mechanism_analysis.json"
OUT_MD = ROOT / "prospective_rsd_v3/jsonpickle_mechanism_analysis.md"
FIG_PDF = ROOT / "paper/figures/jsonpickle_mechanism.pdf"
FIG_PNG = ROOT / "paper/figures/jsonpickle_mechanism.png"

TEAL = "#167D8D"
BRICK = "#B54A3A"
BLUE = "#3F6FB6"
GREY = "#6B7280"
LIGHT = "#F4F6F8"
INK = "#20252B"


def load_jsonl(pattern: str) -> list[dict]:
    rows = []
    for path in sorted(glob.glob(str(ROOT / pattern))):
        with open(path) as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return rows


def exact_sign_flip(effects: list[float]) -> dict:
    observed = abs(sum(effects) / len(effects))
    permuted = []
    for signs in itertools.product((-1, 1), repeat=len(effects)):
        permuted.append(abs(sum(s * x for s, x in zip(signs, effects)) / len(effects)))
    return {
        "observed_mean": sum(effects) / len(effects),
        "two_sided_p": sum(x >= observed - 1e-12 for x in permuted) / len(permuted),
        "assignments": len(permuted),
    }


def conditional_all_successes_in_candidate(hist_n: int, cand_n: int, successes: int) -> float:
    return comb(cand_n, successes) / comb(hist_n + cand_n, successes)


def state_matrix(rows: list[dict]) -> dict[str, dict[str, list[int]]]:
    out: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("anchor_id") == ANCHOR:
            out[row["model"]][row["state_id"]].append(int(bool(row["joint_success"])))
    return {model: {state: sorted(values, reverse=True) for state, values in states.items()}
            for model, states in out.items()}


def rounded_box(ax, xy, width, height, text, fc=LIGHT, ec="#CBD2D9", fontsize=7.0,
                color=INK, family="sans-serif", lw=1.0):
    patch = FancyBboxPatch(xy, width, height, boxstyle="round,pad=0.018,rounding_size=0.025",
                           facecolor=fc, edgecolor=ec, linewidth=lw)
    ax.add_patch(patch)
    ax.text(xy[0] + width / 2, xy[1] + height / 2, text, ha="center", va="center",
            fontsize=fontsize, color=color, family=family, linespacing=1.28)


def render_figure(matrix: dict[str, dict[str, list[int]]]) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titleweight": "bold",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig = plt.figure(figsize=(7.15, 3.05), constrained_layout=True)
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.16, 0.92])

    ax = fig.add_subplot(gs[0, 0]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("a  Current-task primitive", loc="left", fontsize=7.8)
    rounded_box(ax, (0.03, 0.69), 0.94, 0.19,
                "Repeated plain dictionaries\n[x, x] → decoded[0] is decoded[1]",
                fc="#E8F4F5", ec=TEAL)
    rounded_box(ax, (0.08, 0.39), 0.84, 0.20,
                "Candidate states s0 / s1\nPickler: _mkref(dict)\n         or _getref(dict)\nUnpickler: _mkref(dict)",
                fc="white", ec=TEAL, family="DejaVu Sans Mono", fontsize=6.2)
    ax.add_patch(FancyArrowPatch((0.50, 0.68), (0.50, 0.60), arrowstyle="-|>", mutation_scale=11,
                                 color=GREY, linewidth=1.2))
    ax.text(0.5, 0.25, "Same current success;\ndifferent future affordances.",
            ha="center", va="center", fontsize=6.9, color=GREY)

    ax = fig.add_subplot(gs[0, 1]); ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_title("b  Future composition", loc="left", fontsize=7.8)
    rounded_box(ax, (0.03, 0.69), 0.94, 0.19,
                "Dict subclass plus attribute dictionary\n[d, d, d.__dict__] → identities must agree",
                fc="#FFF1EE", ec=BRICK)
    rounded_box(ax, (0.07, 0.39), 0.86, 0.20,
                "Successful candidate-state composition\ndata['__dict__'] =\n    self._flatten(obj.__dict__)",
                fc="white", ec=BLUE, family="DejaVu Sans Mono", fontsize=6.1)
    ax.add_patch(FancyArrowPatch((0.50, 0.68), (0.50, 0.60), arrowstyle="-|>", mutation_scale=11,
                                 color=GREY, linewidth=1.2))
    ax.text(0.5, 0.25,
            "Successful agents reuse the new\nplain-dict reference table; historical\nagents patch decoder IDs.",
            ha="center", va="center", fontsize=6.9, color=GREY)

    ax = fig.add_subplot(gs[0, 2])
    ax.set_title("c  Frozen outcomes", loc="left", fontsize=7.8)
    models = ["gpt-5.6-sol", "gpt-5.6-terra"]
    states = ["Historical", "s0", "s1"]
    data = np.array([[sum(matrix[m][s.lower()]) for s in states] for m in models], dtype=float)
    ax.imshow(data, cmap=plt.matplotlib.colors.ListedColormap(["#F1D6D1", "#E7EEF8", "#B9D9DD", TEAL]),
              vmin=0, vmax=3, aspect="auto")
    for i in range(2):
        for j in range(3):
            ax.text(j, i, f"{int(data[i,j])}/3", ha="center", va="center",
                    color="white" if data[i,j] >= 2 else INK, fontsize=8.5, fontweight="bold")
    ax.set_xticks(range(3), ["Hist.", "s0", "s1"])
    ax.set_yticks(range(2), ["Sol", "Terra"])
    ax.tick_params(length=0)
    for spine in ax.spines.values(): spine.set_visible(False)
    ax.text(0.0, -0.19, "Only Jsonpickle was non-zero among five repository effects.\n"
            "Exact two-sided repository sign-flip p = 1.00;\nleave-Jsonpickle-out effect = 0 for both consumers.",
            transform=ax.transAxes, ha="left", va="top", fontsize=6.5, color=GREY)

    FIG_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PDF, bbox_inches="tight")
    fig.savefig(FIG_PNG, dpi=240, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    sol = load_jsonl("prospective_rsd_v3/symmetric_rollout/*.jsonl") + load_jsonl(
        "prospective_rsd_v3/symmetric_rollout_repeats/*.jsonl")
    terra = load_jsonl("prospective_rsd_v3/symmetric_rollout_terra/*.jsonl")
    rows = sol + terra
    matrix = state_matrix(rows)
    # The four other frozen repositories have zero candidate-minus-historical effects.
    sol_effects = [0.0, 0.0, 0.5, 0.0, 0.0]
    terra_effects = [0.0, 0.0, 1 / 6, 0.0, 0.0]
    analysis = {
        "pair_id": PAIR,
        "mechanism": {
            "current_task": "Register plain dictionaries in the pickler and unpickler reference tables.",
            "future_task": "Preserve identity when a dictionary subclass and its __dict__ are both referenced.",
            "successful_candidate_composition": "data['__dict__'] = self._flatten(obj.__dict__)",
            "interpretation": "The candidate current-task patch exposes a reusable plain-dictionary reference primitive; successful future trajectories compose through it. This is a source-level case study, not a general causal estimate.",
        },
        "joint_success_by_consumer_and_state": matrix,
        "repository_effects": {"gpt-5.6-sol": sol_effects, "gpt-5.6-terra": terra_effects},
        "exact_repository_sign_flip": {
            "gpt-5.6-sol": exact_sign_flip(sol_effects),
            "gpt-5.6-terra": exact_sign_flip(terra_effects),
        },
        "leave_jsonpickle_out_mean_effect": {"gpt-5.6-sol": 0.0, "gpt-5.6-terra": 0.0},
        "within_jsonpickle_conditional_randomization_descriptive": {
            "gpt-5.6-sol": {"historical_successes": 0, "historical_n": 3, "candidate_successes": 3,
                             "candidate_n": 6, "one_sided_p": conditional_all_successes_in_candidate(3, 6, 3)},
            "gpt-5.6-terra": {"historical_successes": 0, "historical_n": 3, "candidate_successes": 1,
                               "candidate_n": 6, "one_sided_p": conditional_all_successes_in_candidate(3, 6, 1)},
        },
    }
    OUT_JSON.write_text(json.dumps(analysis, indent=2) + "\n")
    OUT_MD.write_text(
        "# Jsonpickle source-level mechanism audit\n\n"
        "The current task adds reference registration for plain dictionaries. The later task requires "
        "the same bookkeeping for a dictionary subclass's attribute dictionary. Successful candidate-state "
        "trajectories route `obj.__dict__` through `_flatten`, reusing the earlier primitive. Historical-state "
        "trajectories instead repeatedly modified decoder bookkeeping and did not pass the joint verifier.\n\n"
        "| Consumer | Historical | s0 | s1 | Candidate minus historical |\n"
        "|---|---:|---:|---:|---:|\n"
        "| Sol | 0/3 | 1/3 | 2/3 | +50.0 pp within Jsonpickle |\n"
        "| Terra | 0/3 | 1/3 | 0/3 | +16.7 pp within Jsonpickle |\n\n"
        "Across the five frozen repositories, Jsonpickle is the sole non-zero repository effect. For each "
        "consumer, the exact two-sided sign-flip p-value over repository effects is 1.00 and the "
        "leave-Jsonpickle-out mean effect is 0. These statistics constrain the result to a mechanism case "
        "study and do not support a population-level benefit claim.\n"
    )
    render_figure(matrix)
    print(json.dumps({"json": str(OUT_JSON), "markdown": str(OUT_MD), "pdf": str(FIG_PDF),
                      "png": str(FIG_PNG), "matrix": matrix}, indent=2))


if __name__ == "__main__":
    main()
