#!/usr/bin/env python3
"""Summarize agent-mediated conflict recovery next to the strict heldout outcomes."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from scipy.stats import binomtest

LEVELS = ("historical", "low", "high")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def paired(reference: dict, candidate: dict) -> dict:
    shared = sorted(set(reference) & set(candidate))
    debt = sum(reference[x] and not candidate[x] for x in shared)
    benefit = sum(not reference[x] and candidate[x] for x in shared)
    ties = len(shared) - debt - benefit
    p = binomtest(debt, debt + benefit, 0.5).pvalue if debt + benefit else 1.0
    return {"pairs": len(shared), "debt": debt, "benefit": benefit, "ties": ties,
            "exact_two_sided_p": p}


def mean(xs):
    xs = list(xs)
    return float(sum(xs) / len(xs)) if xs else math.nan


def attempt_tool_calls(row: dict) -> int:
    """Recovery calls paid by an arm, including arms that exhaust the budget."""
    return sum(r.get("consumer", {}).get("tool_calls", 0) for r in row.get("recovery_rounds", []))


def attempt_agent_seconds(row: dict) -> float:
    """Recovery-agent time paid by an arm, excluding replay and future-task time."""
    return sum(r.get("seconds", 0.0) for r in row.get("recovery_rounds", []))


def summarize(strict_rows: list[dict], recovery_rows: list[dict], expected_arms: int) -> dict:
    strict = {(r["future_pair_id"], r["state_level"]): r for r in strict_rows}
    conflict_keys = {k for k, r in strict.items() if r.get("fatal") == "sequential_replay_failed"}
    rec = {(r["future_pair_id"], r["state_level"]): r for r in recovery_rows}
    if set(rec) - conflict_keys:
        raise SystemExit(f"recovery rows outside the frozen conflict arms: {set(rec) - conflict_keys}")
    complete = len(rec) == expected_arms and set(rec) == conflict_keys
    out = {"complete": complete, "conflict_arms": len(conflict_keys), "recovery_rows": len(rec)}
    recovered = [r for r in rec.values() if r.get("recovery_success")]
    exhausted = [r for r in rec.values() if r.get("fatal") == "recovery_rounds_exhausted"]
    verified = [r for r in recovered if r.get("verified_recovery")]
    prior_na = [r for r in recovered if r.get("recovery_prior_test_apply", {}).get("returncode") not in (None, 0)]
    out["recovery"] = {
        "recovered": len(recovered), "verified": len(verified), "arms": len(rec),
        "verified_not_applicable": len(prior_na),
        "verified_failed": len(recovered) - len(verified) - len(prior_na),
        "rounds_per_recovered_arm": dict(Counter(len(r["recovery_rounds"]) for r in recovered)),
        "fatal_reasons": dict(Counter(r.get("fatal") for r in rec.values() if not r.get("recovery_success"))),
        "mean_recovery_tool_calls": mean(r.get("recovery_tool_calls", 0) for r in recovered),
        "mean_recovery_agent_seconds": mean(r.get("recovery_agent_seconds", 0) for r in recovered),
        "mean_attempt_tool_calls_all_arms": mean(attempt_tool_calls(r) for r in rec.values()),
        "mean_attempt_agent_seconds_all_arms": mean(attempt_agent_seconds(r) for r in rec.values()),
        "mean_attempt_rounds_all_arms": mean(len(r.get("recovery_rounds", [])) for r in rec.values()),
        "mean_exhausted_tool_calls": mean(attempt_tool_calls(r) for r in exhausted),
        "mean_exhausted_agent_seconds": mean(attempt_agent_seconds(r) for r in exhausted),
        "mean_resolution_lines": mean(
            sum(x["resolution_numstat"]["added"] + x["resolution_numstat"]["removed"]
                for x in r["recovery_rounds"] if x.get("resolved")) for r in recovered),
        "mean_upstream_commit_lines": mean(
            sum(x["upstream_numstat"]["added"] + x["upstream_numstat"]["removed"]
                for x in r["recovery_rounds"]) for r in recovered),
        "mean_future_tool_calls_after_recovery": mean(
            r.get("consumer", {}).get("tool_calls", 0) for r in recovered),
        "invalid_actions": sum(
            x["consumer"]["invalid_actions"] for r in rec.values() for x in r["recovery_rounds"]),
    }
    # Continuation after recovery, and recovery-inclusive continuation per state.
    out["states"] = {}
    maps_strict = {lvl: {r["future_pair_id"]: r.get("success") is True
                         for r in strict_rows if r["state_level"] == lvl} for lvl in LEVELS}
    maps_incl = {lvl: dict(maps_strict[lvl]) for lvl in LEVELS}
    for lvl in ("low", "high"):
        arms = [r for k, r in rec.items() if k[1] == lvl]
        strict_success = sum(maps_strict[lvl].values())
        rec_success = sum(r.get("success") is True for r in arms)
        for r in arms:
            if r.get("success") is True:
                maps_incl[lvl][r["future_pair_id"]] = True
        executed_after = [r for r in arms if r.get("recovery_success")]
        out["states"][lvl] = {
            "conflict_arms": len(arms),
            "recovered": sum(r.get("recovery_success") is True for r in arms),
            "verified": sum(r.get("verified_recovery") is True for r in arms),
            "success_after_recovery": rec_success,
            "conditional_success_given_recovery": (
                sum(r.get("success") is True for r in executed_after) / len(executed_after)
                if executed_after else math.nan),
            "strict_successes_over_15": strict_success,
            "recovery_inclusive_successes_over_15": strict_success + rec_success,
        }
    out["states"]["historical"] = {"successes_over_15": sum(maps_strict["historical"].values())}
    out["paired_recovery_inclusive"] = {
        f"historical_vs_{lvl}": paired(maps_incl["historical"], maps_incl[lvl]) for lvl in ("low", "high")}
    out["paired_recovery_inclusive"]["low_vs_high"] = paired(maps_incl["low"], maps_incl["high"])
    # Per anchor.
    anchors = sorted({r["anchor_id"] for r in strict_rows})
    out["anchors"] = {}
    for a in anchors:
        entry = {}
        for lvl in LEVELS:
            s = [r for r in strict_rows if r["anchor_id"] == a and r["state_level"] == lvl]
            rr = [r for k, r in rec.items() if k[1] == lvl and r["anchor_id"] == a]
            entry[lvl] = {
                "strict_successes": sum(r.get("success") is True for r in s),
                "arms": len(s),
                "conflicts": sum(r.get("fatal") == "sequential_replay_failed" for r in s),
                "recovered": sum(r.get("recovery_success") is True for r in rr),
                "verified": sum(r.get("verified_recovery") is True for r in rr),
                "success_after_recovery": sum(r.get("success") is True for r in rr),
            }
        out["anchors"][a] = entry
    out["arm_outcomes"] = {
        f"{k[0]}|{k[1]}": {
            "recovered": r.get("recovery_success") is True,
            "verified": r.get("verified_recovery") is True,
            "success": r.get("success") is True,
            "rounds": len(r.get("recovery_rounds", [])),
            "fatal": r.get("fatal"),
        } for k, r in sorted(rec.items())}
    return out


def summarize_extended(rows: list[dict], frozen_rows: list[dict]) -> dict:
    """Extended-budget sensitivity over the arms that exhausted the frozen three-round budget."""
    frozen = {(r["future_pair_id"], r["state_level"]): r for r in frozen_rows
              if r.get("fatal") == "recovery_rounds_exhausted"}
    rec = {(r["future_pair_id"], r["state_level"]): r for r in rows}
    if set(rec) - set(frozen):
        raise SystemExit(f"extended rows outside the exhausted arms: {set(rec) - set(frozen)}")
    recovered = [r for r in rec.values() if r.get("recovery_success")]
    out = {"complete": set(rec) == set(frozen), "exhausted_arms": len(frozen), "rows": len(rec),
           "recovered": len(recovered),
           "verified": sum(r.get("verified_recovery") is True for r in recovered),
           "verified_not_applicable": sum(r.get("recovery_prior_test_apply", {}).get("returncode") not in (None, 0) for r in recovered),
           "success": sum(r.get("success") is True for r in recovered),
           "future_regression_failed_after_recovery": sum(
               r.get("successor_regression_test", {}).get("returncode") not in (None, 0) for r in recovered),
           "future_oracle_failed_after_recovery": sum(
               r.get("successor_oracle_test", {}).get("returncode") not in (None, 0) for r in recovered),
           "rounds_used": dict(Counter(len(r["recovery_rounds"]) for r in rec.values())),
           "fatal_reasons": dict(Counter(r.get("fatal") for r in rec.values() if not r.get("recovery_success"))),
           "mean_recovery_tool_calls": mean(r.get("recovery_tool_calls", 0) for r in recovered),
           "mean_recovery_agent_seconds": mean(r.get("recovery_agent_seconds", 0) for r in recovered),
           "distinct_conflict_commits_per_arm": {
               f"{k[0]}|{k[1]}": len({x["conflict_commit"] for x in r["recovery_rounds"]}
                                  | ({r["unresolved_conflict"]["commit"]} if r.get("unresolved_conflict") else set()))
               for k, r in sorted(rec.items())},
           "arm_outcomes": {f"{k[0]}|{k[1]}": {
               "recovered": r.get("recovery_success") is True, "verified": r.get("verified_recovery") is True,
               "success": r.get("success") is True, "rounds": len(r.get("recovery_rounds", [])),
               "fatal": r.get("fatal")} for k, r in sorted(rec.items())}}
    by_anchor = {}
    for k, r in rec.items():
        a = r["anchor_id"]
        d = by_anchor.setdefault(a, {"arms": 0, "recovered": 0, "success": 0})
        d["arms"] += 1; d["recovered"] += r.get("recovery_success") is True; d["success"] += r.get("success") is True
    out["by_anchor"] = by_anchor
    # Recovery-inclusive per state if the extended budget had been the protocol.
    out["states_if_extended"] = {}
    for lvl in ("low", "high"):
        extra = sum(r.get("success") is True for k, r in rec.items() if k[1] == lvl)
        out["states_if_extended"][lvl] = {"additional_successes": extra}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-extended", type=Path)
    parser.add_argument("--claude-extended", type=Path)
    parser.add_argument("--codex-heldout", required=True, type=Path)
    parser.add_argument("--claude-heldout", required=True, type=Path)
    parser.add_argument("--codex-recovery", required=True, type=Path)
    parser.add_argument("--claude-recovery", required=True, type=Path)
    parser.add_argument("--expected-arms", type=int, default=20)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    codex_strict, claude_strict = read_jsonl(args.codex_heldout), read_jsonl(args.claude_heldout)
    result = {
        "codex": summarize(codex_strict, read_jsonl(args.codex_recovery), args.expected_arms),
        "claude": summarize(claude_strict, read_jsonl(args.claude_recovery), args.expected_arms),
    }
    # Executed-arm agreement (arms where both consumers actually ran under the strict protocol).
    cx = {(r["future_pair_id"], r["state_level"]): r for r in codex_strict}
    cl = {(r["future_pair_id"], r["state_level"]): r for r in claude_strict}
    executed = [k for k in cx if cx[k].get("fatal") != "sequential_replay_failed"
                and cl[k].get("fatal") != "sequential_replay_failed"]
    agree = sum((cx[k].get("success") is True) == (cl[k].get("success") is True) for k in executed)
    result["strict_cross_consumer"] = {
        "all_arms": len(cx), "all_agree": sum(
            (cx[k].get("success") is True) == (cl[k].get("success") is True) for k in cx),
        "executed_arms": len(executed), "executed_agree": agree,
        "mechanically_identical_conflict_arms": len(cx) - len(executed),
    }
    rc = {k: v for k, v in result["codex"]["arm_outcomes"].items()}
    rl = {k: v for k, v in result["claude"]["arm_outcomes"].items()}
    shared = sorted(set(rc) & set(rl))
    result["recovery_cross_consumer"] = {
        "shared_arms": len(shared),
        "recovery_agree": sum(rc[k]["recovered"] == rl[k]["recovered"] for k in shared),
        "success_agree": sum(rc[k]["success"] == rl[k]["success"] for k in shared),
    }
    if args.codex_extended:
        result["extended_budget_codex"] = summarize_extended(read_jsonl(args.codex_extended), read_jsonl(args.codex_recovery))
    if args.claude_extended:
        result["extended_budget_claude"] = summarize_extended(read_jsonl(args.claude_extended), read_jsonl(args.claude_recovery))
    result = json.loads(json.dumps(result, default=dict))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=True) + "\n")
    print(json.dumps({c: {"recovery": result[c]["recovery"], "states": result[c]["states"]}
                      for c in ("codex", "claude")}, indent=1, allow_nan=True))
    print(json.dumps({k: result[k] for k in ("strict_cross_consumer", "recovery_cross_consumer")}, indent=1))


if __name__ == "__main__":
    main()
