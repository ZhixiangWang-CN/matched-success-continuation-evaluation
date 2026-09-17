#!/usr/bin/env python3
"""Exploratory transfer audit for the frozen continuation-selection panel.

This analysis was specified after the primary claim gate was opened and must
not be presented as confirmatory evidence for the selection-policy claim.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path

import numpy as np


def centered_correlation(x: np.ndarray, y: np.ndarray, groups: list[object]) -> tuple[float, np.ndarray]:
    keep = np.zeros(len(x), dtype=bool)
    xc = x.copy()
    yc = y.copy()
    for group in sorted(set(groups), key=str):
        index = np.asarray([i for i, value in enumerate(groups) if value == group])
        xc[index] -= xc[index].mean()
        yc[index] -= yc[index].mean()
        if len(index) > 1:
            keep[index] = True
    return float(np.corrcoef(xc[keep], yc[keep])[0, 1]), keep


def permutation_p(
    x: np.ndarray,
    y: np.ndarray,
    groups: list[object],
    observed: float,
    repeats: int,
    seed: int,
) -> float:
    rng = np.random.default_rng(seed)
    greater = 0
    unique = sorted(set(groups), key=str)
    for _ in range(repeats):
        permuted = y.copy()
        for group in unique:
            index = np.asarray([i for i, value in enumerate(groups) if value == group])
            permuted[index] = rng.permutation(permuted[index])
        statistic, _ = centered_correlation(x, permuted, groups)
        greater += statistic >= observed - 1e-12
    return float((greater + 1) / (repeats + 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-dir", required=True, type=Path)
    parser.add_argument("--results", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--permutations", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20260911)
    args = parser.parse_args()

    states = [json.loads(line) for line in (args.protocol_dir / "frozen_states.jsonl").read_text().splitlines() if line]
    rows = []
    for path in args.results:
        rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    grouped: dict[tuple[str, str], list[float]] = collections.defaultdict(list)
    for row in rows:
        grouped[(row["family"], row["state_sha256"])].append(float(row["future_success"]))
    if len(rows) != 384 or len(grouped) != len(states):
        raise RuntimeError(f"Coverage failure: rows={len(rows)}, states={len(grouped)}")

    x = np.asarray([state["development_value"] for state in states], dtype=float)
    y = np.asarray([np.mean(grouped[(state["family"], state["state_sha256"])]) for state in states], dtype=float)
    family = [state["family"] for state in states]
    family_producer = [(state["family"], state["producer"]) for state in states]

    output = {"status": "post-hoc exploratory; not the frozen primary claim gate"}
    for name, groups in (("within_family", family), ("within_family_producer", family_producer)):
        observed, keep = centered_correlation(x, y, groups)
        output[name] = {
            "pearson_r": observed,
            "n_states_in_nonsingleton_groups": int(keep.sum()),
            "one_sided_within_group_permutation_p": permutation_p(
                x, y, groups, observed, args.permutations, args.seed
            ),
            "permutations": args.permutations,
        }

    leave_one_family_out = {}
    for heldout_family in sorted(set(family)):
        keep_index = np.asarray([value != heldout_family for value in family])
        subgroups = [group for group, keep in zip(family_producer, keep_index) if keep]
        correlation, usable = centered_correlation(x[keep_index], y[keep_index], subgroups)
        leave_one_family_out[heldout_family] = {
            "pearson_r": correlation,
            "n_states_in_nonsingleton_groups": int(usable.sum()),
        }
    output["within_family_producer_leave_one_family_out"] = leave_one_family_out

    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
