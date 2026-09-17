#!/usr/bin/env python3
"""Summarize frozen sequential-replay experiments without post-hoc exclusions."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import binomtest


LEVELS = ("historical", "low", "high")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def wilson(k: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if not n:
        return [math.nan, math.nan]
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [center - half, center + half]


def paired(reference: dict[str, bool], candidate: dict[str, bool]) -> dict:
    shared = sorted(set(reference) & set(candidate))
    debt = sum(reference[x] and not candidate[x] for x in shared)
    benefit = sum(not reference[x] and candidate[x] for x in shared)
    ties = len(shared) - debt - benefit
    p = binomtest(debt, debt + benefit, 0.5).pvalue if debt + benefit else 1.0
    return {"pairs": len(shared), "debt": debt, "benefit": benefit,
            "ties": ties, "exact_two_sided_p": p}


def summarize_heldout(rows: list[dict]) -> dict:
    expected = 45
    if len(rows) != expected:
        raise SystemExit(f"heldout is incomplete: expected {expected}, found {len(rows)}")
    by_key = {(r["future_pair_id"], r["state_level"]): r for r in rows}
    if len(by_key) != expected:
        raise SystemExit("heldout contains duplicate or missing future/state keys")
    anchors = sorted({r["anchor_id"] for r in rows})
    result = {"n_arms": len(rows), "n_anchors": len(anchors),
              "n_futures": len({r['future_pair_id'] for r in rows}),
              "strict_failure_definition": "Every non-True success, including hard replay conflict, is failure",
              "states": {}, "anchors": {}}
    maps = {}
    for level in LEVELS:
        subset = [r for r in rows if r["state_level"] == level]
        k = sum(r.get("success") is True for r in subset)
        replay_fail = sum(r.get("fatal") == "sequential_replay_failed" for r in subset)
        executed = [r for r in subset if r.get("fatal") != "sequential_replay_failed"]
        maps[level] = {r["future_pair_id"]: r.get("success") is True for r in subset}
        result["states"][level] = {
            "successes": k, "arms": len(subset), "rate": k / len(subset),
            "wilson95": wilson(k, len(subset)), "hard_replay_failures": replay_fail,
            "consumer_executed": len(executed),
            "conditional_success_given_replay": (
                sum(r.get("success") is True for r in executed) / len(executed) if executed else math.nan
            ),
            "mean_seconds_when_executed": (
                float(np.mean([r.get("seconds", 0.0) for r in executed])) if executed else math.nan
            ),
            "mean_tool_calls_when_executed": (
                float(np.mean([r.get("consumer", {}).get("tool_calls", 0) for r in executed]))
                if executed else math.nan
            ),
        }
    result["paired_historical_vs_low"] = paired(maps["historical"], maps["low"])
    result["paired_historical_vs_high"] = paired(maps["historical"], maps["high"])
    result["low_vs_high"] = paired(maps["low"], maps["high"])
    for anchor in anchors:
        subset = [r for r in rows if r["anchor_id"] == anchor]
        result["anchors"][anchor] = {
            level: {
                "successes": sum(r.get("success") is True for r in subset if r["state_level"] == level),
                "arms": sum(r["state_level"] == level for r in subset),
                "hard_replay_failures": sum(
                    r["state_level"] == level and r.get("fatal") == "sequential_replay_failed"
                    for r in subset
                ),
            } for level in LEVELS
        }
    result["invalid_actions"] = sum(
        r.get("consumer", {}).get("invalid_actions", 0) for r in rows
    )
    result["tool_calls"] = sum(r.get("consumer", {}).get("tool_calls", 0) for r in rows)
    return result


def summarize_calibration(rows: list[dict], expected: int = 15) -> dict:
    calls = sum(r.get("consumer", {}).get("tool_calls", 0) for r in rows)
    invalid = sum(r.get("consumer", {}).get("invalid_actions", 0) for r in rows)
    successes = sum(r.get("success") is True for r in rows)
    changed = sum(bool(r.get("changed_by_agent")) for r in rows)
    return {
        "complete": len(rows) == expected, "rollouts": len(rows), "expected": expected,
        "successes": successes, "success_rate": successes / len(rows) if rows else math.nan,
        "changed": changed, "changed_rate": changed / len(rows) if rows else math.nan,
        "tool_calls": calls, "invalid_actions": invalid,
        "invalid_rate": invalid / calls if calls else math.nan,
        "gate_pass": (len(rows) == expected and successes / expected >= 0.30
                      and changed / expected >= 0.80 and (invalid / calls if calls else 1) < 0.05),
        "by_anchor": {
            anchor: {"successes": sum(r.get("success") is True for r in rows if r["anchor_id"] == anchor),
                     "rollouts": sum(r["anchor_id"] == anchor for r in rows)}
            for anchor in sorted({r["anchor_id"] for r in rows})
        },
    }


def plot(summary: dict, path: Path) -> None:
    anchors = list(summary["anchors"])
    labels = [x.split("__")[0].replace("researchobject", "ro-crate") for x in anchors]
    values = np.array([[summary["anchors"][a][level]["successes"] / 3
                        for level in LEVELS] for a in anchors])
    x = np.arange(len(anchors))
    fig, ax = plt.subplots(figsize=(8.2, 3.6))
    colors = ["#3B5B92", "#D69E2E", "#B6463A"]
    for i, (level, color) in enumerate(zip(LEVELS, colors)):
        ax.bar(x + (i - 1) * 0.23, values[:, i], width=0.22,
               label=level.capitalize(), color=color)
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Strict continuation success")
    ax.set_xlabel("Frozen anchor (3 held-out futures each)")
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=220)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heldout", required=True, type=Path)
    parser.add_argument("--claude-heldout", type=Path)
    parser.add_argument("--claude-calibration", type=Path)
    parser.add_argument("--stochastic-repeats", type=Path)
    parser.add_argument("--deterministic-repeats", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--figure", required=True, type=Path)
    args = parser.parse_args()
    codex_rows = read_jsonl(args.heldout)
    result = {"heldout_codex": summarize_heldout(codex_rows)}
    if args.claude_heldout:
        claude_rows = read_jsonl(args.claude_heldout)
        result["heldout_claude"] = summarize_heldout(claude_rows)
        codex = {(r["future_pair_id"], r["state_level"]): r.get("success") is True
                 for r in codex_rows}
        claude = {(r["future_pair_id"], r["state_level"]): r.get("success") is True
                  for r in claude_rows}
        shared = sorted(set(codex) & set(claude))
        result["cross_consumer"] = {
            "shared_arms": len(shared),
            "outcome_agreement": sum(codex[k] == claude[k] for k in shared) / len(shared),
            "disagreements": [
                {"future_pair_id": k[0], "state_level": k[1],
                 "codex": codex[k], "claude": claude[k]}
                for k in shared if codex[k] != claude[k]
            ],
        }
    if args.claude_calibration:
        result["claude_calibration"] = summarize_calibration(read_jsonl(args.claude_calibration))
    if args.stochastic_repeats:
        rows = read_jsonl(args.stochastic_repeats)
        result["stochastic_repeats_additional"] = {
            "complete": len(rows) == 6, "rollouts": len(rows),
            "by_state": {level: Counter(
                "success" if r.get("success") is True else "failure"
                for r in rows if r.get("state_level") == level
            ) for level in LEVELS},
        }
    if args.deterministic_repeats:
        rows = read_jsonl(args.deterministic_repeats)
        result["deterministic_repeats"] = {
            "complete": len(rows) == 6, "rollouts": len(rows),
            "replay_failures": sum(not r.get("replay_success", False) for r in rows),
            "conflict_signatures": Counter(
                f"{r.get('conflict_commit')}:{','.join(r.get('conflict_files', []))}" for r in rows
            ),
        }
    # Convert Counter objects to plain dicts for a stable artifact.
    result = json.loads(json.dumps(result, default=dict))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=True) + "\n")
    plot(result["heldout_codex"], args.figure)
    print(json.dumps(result, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
