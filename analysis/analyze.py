#!/usr/bin/env python3
"""Summarize paired Epistemic Echo experiment results."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()

    rows = []
    for filename in args.inputs:
        for line in Path(filename).read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))

    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["model"], row["condition"])].append(row)

    summary = {"models": {}, "definitions": {
        "echo_action_inflation": "ACT rate(paraphrase_echo) - ACT rate(single)",
        "independence_sensitivity": "ACT rate(independent) - ACT rate(paraphrase_echo)",
        "echo_confidence_inflation": "mean p(paraphrase_echo) - mean p(single)",
    }}
    models = sorted({row["model"] for row in rows})
    for model in models:
        conditions = {}
        for condition in ("single", "verbatim_echo", "paraphrase_echo", "independent"):
            items = grouped[(model, condition)]
            conditions[condition] = {
                "n": len(items),
                "parse_rate": mean([1.0 if r.get("parsed") else 0.0 for r in items]),
                "act_rate": mean([1.0 if r.get("action") == "ACT" else 0.0 for r in items if r.get("action")]),
                "mean_probability_true": mean([r.get("probability_true") for r in items]),
                "normative_accuracy": mean([1.0 if r.get("action") == r["normative_action"] else 0.0 for r in items if r.get("action")]),
            }
        s, e, i = conditions["single"], conditions["paraphrase_echo"], conditions["independent"]
        effects = {
            "echo_action_inflation": e["act_rate"] - s["act_rate"],
            "independence_sensitivity": i["act_rate"] - e["act_rate"],
            "echo_confidence_inflation": e["mean_probability_true"] - s["mean_probability_true"],
            "independent_confidence_gain": i["mean_probability_true"] - e["mean_probability_true"],
        }
        summary["models"][model] = {"conditions": conditions, "effects": effects}

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n")


if __name__ == "__main__":
    main()
