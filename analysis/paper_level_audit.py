#!/usr/bin/env python3
"""Final, assumption-explicit audit for the deep residual-state experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def load_jsonl(paths):
    rows = []
    for path in paths:
        rows.extend(json.loads(line) for line in Path(path).read_text().splitlines() if line.strip())
    return rows


def mean(xs):
    return float(np.mean(xs)) if xs else None


def wilson(successes, n, z=1.959963984540054):
    if not n:
        return [None, None]
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [center - half, center + half]


def paired_sign_test(clean, debt):
    clean_only = sum(c and not d for c, d in zip(clean, debt))
    debt_only = sum(d and not c for c, d in zip(clean, debt))
    n = clean_only + debt_only
    if n == 0:
        p = 1.0
    else:
        k = min(clean_only, debt_only)
        tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
        p = min(1.0, 2 * tail)
    return {"clean_only": clean_only, "debt_only": debt_only, "discordant_n": n,
            "exact_two_sided_p": p}


def dynamics(rows):
    cells = defaultdict(list)
    keyed = defaultdict(dict)
    for r in rows:
        cells[(r["model"], int(r["dose"]), r["state"])].append(bool(r["future_success"]))
        keyed[(r["model"], int(r["dose"]), r["future_id"], int(r["sample"]))][r["state"]] = bool(r["future_success"])
    out = {"cells": {}, "paired_contrasts": {}, "dose_slopes": {}}
    for key, vals in sorted(cells.items()):
        out["cells"]["|".join(map(str, key))] = {
            "n": len(vals), "success": mean(vals), "wilson_95ci": wilson(sum(vals), len(vals))}
    for model in sorted({r["model"] for r in rows}):
        for dose in (20, 50, 100):
            pairs = [v for k, v in keyed.items() if k[0] == model and k[1] == dose and {"clean", "debt"} <= set(v)]
            c, d = [v["clean"] for v in pairs], [v["debt"] for v in pairs]
            sm = [v for k, v in keyed.items() if k[0] == model and k[1] == dose and {"clean_size_matched", "debt"} <= set(v)]
            mc, md = [v["clean_size_matched"] for v in sm], [v["debt"] for v in sm]
            out["paired_contrasts"][f"{model}|{dose}"] = {
                "clean_minus_debt": mean(c) - mean(d), "clean_vs_debt": paired_sign_test(c, d),
                "size_matched_clean_minus_debt": mean(mc) - mean(md),
                "size_matched_clean_vs_debt": paired_sign_test(mc, md)}
        debt20 = mean(cells[(model, 20, "debt")])
        debt100 = mean(cells[(model, 100, "debt")])
        clean20 = mean(cells[(model, 20, "clean")])
        clean100 = mean(cells[(model, 100, "clean")])
        matched20 = mean(cells[(model, 20, "clean_size_matched")])
        matched100 = mean(cells[(model, 100, "clean_size_matched")])
        out["dose_slopes"][model] = {
            "debt_success_100_minus_20": debt100 - debt20,
            "difference_in_differences_clean": (clean100 - debt100) - (clean20 - debt20),
            "difference_in_differences_size_matched": (matched100 - debt100) - (matched20 - debt20)}
    return out


def recovery(rows):
    out = {}
    for model in sorted({r["model"] for r in rows}):
        mr = [r for r in rows if r["model"] == model and r["record_type"] == "repair"]
        post = [r for r in rows if r["model"] == model and r["record_type"] == "post_repair_continuation"]
        verified = [r for r in post if r["repair_success"]]
        k = sum(bool(r["repair_success"]) for r in mr)
        out[model] = {
            "repair_attempts": len(mr), "verified_repairs": k,
            "verified_repair_rate": mean([r["repair_success"] for r in mr]),
            "verified_repair_rate_wilson_95ci": wilson(k, len(mr)),
            "current_behavior_preserved": mean([r["current_success"] for r in mr]),
            "post_repair_continuation": mean([r["future_success"] for r in post]),
            "post_repair_given_verified": mean([r["future_success"] for r in verified]),
            "mean_repair_tokens": mean([r["completion_tokens"] for r in mr]),
            "mean_model_edit_cost": mean([r["repair_edit_cost"] for r in mr]),
            "mean_exact_rollback_edit_cost": mean([r["exact_rollback_edit_cost"] for r in mr])}
    return out


def goodhart(rows):
    out = {}
    for model in sorted({r["model"] for r in rows}):
        x = [r for r in rows if r["model"] == model]
        by = {s: [r["future_success"] for r in x if r["state"] == s]
              for s in ("camouflaged_debt", "stigmatized_clean")}
        out[model] = {
            "camouflaged_debt_success": mean(by["camouflaged_debt"]),
            "stigmatized_clean_success": mean(by["stigmatized_clean"]),
            "semantic_gap_stigmatized_minus_camouflaged": mean(by["stigmatized_clean"]) - mean(by["camouflaged_debt"]),
            "n_per_state": {k: len(v) for k, v in by.items()}}
    return out


def integrity(root, expected_models):
    expected = {
        "coding": (expected_models, 144),
        "enterprise": (expected_models, 96),
        "natural_producer": (expected_models, 18),
        "natural_successor": (["llama3_8b", "qwen25_72b", "qwen25_7b"], 312),
        "recovery": (["qwen25_72b", "qwen25_7b"], 60),
        "dynamics": (expected_models, 72),
        "goodhart": (["qwen25_72b", "qwen25_7b"], 96),
        "judge": (expected_models, 60)}
    files = {}
    failures = []
    for path in sorted(root.glob("*.jsonl")):
        n = sum(1 for line in path.read_text().splitlines() if line.strip())
        files[path.name] = {"lines": n, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    for kind, (kind_models, expected_n) in expected.items():
        for model in kind_models:
            name = f"{kind}_{model}.jsonl" if kind not in ("coding", "enterprise") else f"{model}_{kind}.jsonl"
            if name not in files:
                failures.append(f"missing:{name}")
            elif files[name]["lines"] != expected_n:
                failures.append(f"count:{name}:{files[name]['lines']}!={expected_n}")
    return {"expected_models": expected_models, "files": files, "failures": failures, "passed": not failures}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="empirical_results")
    ap.add_argument("--output", default="empirical_results/paper_level_audit.json")
    args = ap.parse_args()
    root = Path(args.root)
    models = ["gemma2_9b", "llama3_8b", "phi35", "qwen25_72b", "qwen25_7b"]
    dyn = load_jsonl(root.glob("dynamics_*.jsonl"))
    rec = load_jsonl(root.glob("recovery_*.jsonl"))
    good = load_jsonl(root.glob("goodhart_*.jsonl"))
    result = {
        "scope_note": "Executable micro-environments; model/family are the intended generalization units.",
        "integrity": integrity(root, models),
        "dynamics": dynamics(dyn),
        "recovery": recovery(rec),
        "goodhart": goodhart(good),
    }
    for name in ("coding_scale_summary", "enterprise_scale_summary", "terminal_state_critic",
                 "distribution_robustness", "natural_states_summary", "natural_state_selection",
                 "advanced_natural_state_critic", "state_judges_summary", "goodhart_critic"):
        path = root / f"{name}.json"
        if path.exists():
            result[name] = json.loads(path.read_text())
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
