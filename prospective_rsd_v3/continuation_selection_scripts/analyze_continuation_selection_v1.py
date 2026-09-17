#!/usr/bin/env python3
"""Analyze the frozen continuation-aware selection experiment."""

from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-dir", required=True, type=Path)
    parser.add_argument("--results", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bootstrap", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()

    protocol = json.loads((args.protocol_dir / "protocol.json").read_text())
    selectors = json.loads((args.protocol_dir / "frozen_selectors.json").read_text())
    states = [json.loads(line) for line in (args.protocol_dir / "frozen_states.jsonl").read_text().splitlines() if line]
    tasks = json.loads((args.protocol_dir / "frozen_heldout_tasks.json").read_text())
    all_rows = []
    for path in args.results:
        all_rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    key_fields = ("consumer", "family", "state_sha256", "future_id", "repeat")
    keyed = {tuple(row[field] for field in key_fields): row for row in all_rows}
    duplicate_rows = len(all_rows) - len(keyed)

    consumers = sorted({row["consumer"] for row in keyed.values()})
    if len(consumers) != 1:
        raise RuntimeError(f"Expected one frozen consumer, found {consumers}")
    expected = set()
    for state in states:
        for future_id, _requirement, _test in tasks[state["family"]]:
            for repeat in range(protocol["repeats"]):
                expected.add((consumers[0], state["family"], state["state_sha256"], future_id, repeat))
    missing = sorted(expected - set(keyed))
    extra = sorted(set(keyed) - expected)
    if missing or extra or duplicate_rows:
        raise RuntimeError(f"Coverage failure: missing={len(missing)} extra={len(extra)} duplicates={duplicate_rows}")

    by_state = defaultdict(list)
    by_state_future = defaultdict(list)
    for key, row in keyed.items():
        _consumer, family, state_sha, future_id, _repeat = key
        value = float(row["future_success"])
        by_state[(family, state_sha)].append(value)
        by_state_future[(family, state_sha, future_id)].append(value)
    state_value = {key: float(np.mean(values)) for key, values in by_state.items()}

    family_rows = []
    candidate_vectors = []
    for family in sorted(selectors):
        candidates = sorted([state["state_sha256"] for state in states if state["family"] == family])
        values = np.asarray([state_value[(family, state)] for state in candidates])
        continuation_sha = selectors[family]["continuation_selected_sha256"]
        shortest_sha = selectors[family]["shortest_selected_sha256"]
        continuation_value = state_value[(family, continuation_sha)]
        shortest_value = state_value[(family, shortest_sha)]
        random_value = float(values.mean())
        oracle_value = float(values.max())
        candidate_vectors.append(values)
        family_rows.append({
            "family": family,
            "n_candidates": len(candidates),
            "continuation_selected_sha256": continuation_sha,
            "shortest_selected_sha256": shortest_sha,
            "continuation_value": continuation_value,
            "current_success_random_value": random_value,
            "shortest_value": shortest_value,
            "heldout_oracle_value": oracle_value,
            "continuation_minus_random": continuation_value - random_value,
            "continuation_minus_shortest": continuation_value - shortest_value,
            "continuation_regret": oracle_value - continuation_value,
            "future_values": {
                future_id: float(np.mean(by_state_future[(family, continuation_sha, future_id)]))
                for future_id, _requirement, _test in tasks[family]
            },
        })

    observed = float(np.mean([row["continuation_value"] for row in family_rows]))
    random_baseline = float(np.mean([row["current_success_random_value"] for row in family_rows]))
    shortest_baseline = float(np.mean([row["shortest_value"] for row in family_rows]))
    observed_effect = observed - random_baseline
    static_effect = observed - shortest_baseline

    total_combinations = int(np.prod([len(values) for values in candidate_vectors]))
    if total_combinations <= 5_000_000:
        null_values = np.fromiter(
            (sum(choice) / len(choice) for choice in itertools.product(*candidate_vectors)),
            dtype=float,
            count=total_combinations,
        )
        p_random = float((1 + np.sum(null_values >= observed - 1e-12)) / (1 + len(null_values)))
        null_method = "exact enumeration over one uniformly chosen current-success state per family"
    else:
        rng = np.random.default_rng(args.seed)
        null_values = np.asarray([
            np.mean([rng.choice(values) for values in candidate_vectors]) for _ in range(1_000_000)
        ])
        p_random = float((1 + np.sum(null_values >= observed - 1e-12)) / (1 + len(null_values)))
        null_method = "one-million-draw Monte Carlo random selection distribution"

    effects = np.asarray([row["continuation_minus_random"] for row in family_rows])
    static_effects = np.asarray([row["continuation_minus_shortest"] for row in family_rows])
    rng = np.random.default_rng(args.seed)
    draws = rng.integers(0, len(family_rows), size=(args.bootstrap, len(family_rows)))
    boot_effect = effects[draws].mean(axis=1)
    boot_static = static_effects[draws].mean(axis=1)

    out = {
        "protocol": protocol["protocol"],
        "consumer": consumers[0],
        "coverage": {
            "rows": len(keyed),
            "expected_rows": len(expected),
            "families": len(family_rows),
            "states": len(states),
            "futures": sum(len(v) for v in tasks.values()),
            "repeats": protocol["repeats"],
            "current_preservation": Counter(row["current_preserved"] for row in keyed.values()),
        },
        "primary": {
            "continuation_selected_value": observed,
            "current_success_random_value": random_baseline,
            "effect": observed_effect,
            "family_cluster_bootstrap_95_ci": [float(x) for x in np.quantile(boot_effect, [0.025, 0.975])],
            "random_selection_p_one_sided": p_random,
            "random_selection_null_method": null_method,
            "random_selection_combinations": total_combinations,
            "claim_gate_pass": bool(observed_effect > 0 and p_random < 0.05),
        },
        "static_baseline": {
            "shortest_value": shortest_baseline,
            "effect": static_effect,
            "family_cluster_bootstrap_95_ci": [float(x) for x in np.quantile(boot_static, [0.025, 0.975])],
        },
        "families": family_rows,
        "warning": "Held-out outcomes are prospective relative to this frozen protocol, but the task suite and analysis were designed after earlier project results were known. The experiment is confirmatory for the frozen panel, not a prevalence estimate.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True, default=lambda x: dict(x)) + "\n")
    print(json.dumps(out["primary"] | {"shortest_value": shortest_baseline, "continuation_minus_shortest": static_effect}, indent=2))


if __name__ == "__main__":
    main()
