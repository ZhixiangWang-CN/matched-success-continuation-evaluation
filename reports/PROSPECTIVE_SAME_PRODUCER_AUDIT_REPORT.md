# Prospective Same-Producer Audit Report

## Scope and preregistration status

This extension tests whether independently generated terminal states that all solve the same current repository task remain equally usable after the repository evolves. Candidate generation, current-task verification, future selection, and the consumer calibration gate were frozen before heldout evaluation. All results in this report use the single designated audit future per anchor. The three heldout futures per anchor remain unopened.

## Candidate construction

One fixed Qwen3.6-35B-A3B producer generated 12 trajectories for each of 19 repository-disjoint anchors (228/228 operationally valid rollouts). Of 154 nonempty patches, 52 passed syntax checks, test-edit exclusion, the current hidden and regression tests, and the frozen metamorphic verifier. Deduplication left 41 unique current-success states. The prospective continuation bank retained the five anchors with at least three unique candidates, yielding 35 candidate states: Moto (10), Jsonpickle (5), Kinto (8), Pymodbus (3), and RO-Crate (9).

## Future-consumer calibration

The planned outcome was autonomous future-task success. Before candidate comparison, the consumer had to solve at least 30% of historical-gold controls, change code in at least 80% of rollouts, and produce fewer than 5% invalid actions. The final audit-only calibration used Qwen3.6-35B-A3B, 30 steps, three fixed seeds, verification before editing, and network isolation. It solved 3/15 controls (20.0%), changed code in 5/15 (33.3%), and produced 1/384 invalid actions (0.26%). The sensitivity gate therefore failed. No autonomous-agent candidate contrast was run on heldout futures.

| Audit anchor | Controls | Success | Code changed |
|---|---:|---:|---:|
| Moto | 3 | 0 | 0 |
| Jsonpickle | 3 | 0 | 0 |
| Kinto | 3 | 3 | 3 |
| Pymodbus | 3 | 0 | 0 |
| RO-Crate | 3 | 0 | 2 |
| **Total** | **15** | **3 (20.0%)** | **5 (33.3%)** |

The failure is strongly task-dependent rather than a parser failure: invalid actions are below threshold, but four of five future tasks remain effectively unsolved. Candidate-state continuation success under this consumer would therefore be dominated by executor floor effects.

## Deterministic counterfactual-transport audit

We next ran an audit-only diagnostic that does not claim autonomous future-task completion. For each candidate, we computed its exact tree delta relative to the historical current-task solution and attempted to transport that delta to the frozen future repository base using three-way application with direct and fuzzy fallbacks. This operation asks whether the alternative current-success state can be propagated through the observed repository evolution without manual reconciliation.

All 5/5 historical controls were transportable. Only 20/35 generated states (57.1%) were transportable; 15/35 (42.9%) required manual reconciliation. Every failed transport included a source-code conflict, in `jsonpickle/pickler.py`, `jsonpickle/unpickler.py`, `kinto/core/authorization.py`, or `pymodbus/diag_message.py`. The failure is not explained by larger deltas: the median candidate-to-historical delta was 49 lines among incompatible states and 59.5 among compatible states. All 20 successfully transported states remained compatible with the audit future's maintainer patch.

| Anchor | Candidate states | Transportable | Manual reconciliation required | Future patch mergeable after transport |
|---|---:|---:|---:|---:|
| Moto | 10 | 10 | 0 | 10/10 |
| Jsonpickle | 5 | 0 | 5 | 0/0 eligible |
| Kinto | 8 | 0 | 8 | 0/0 eligible |
| Pymodbus | 3 | 1 | 2 | 1/1 |
| RO-Crate | 9 | 9 | 0 | 9/9 |
| **Total** | **35** | **20 (57.1%)** | **15 (42.9%)** | **20/20 eligible** |

## Interpretation

The audit establishes a prospective same-producer compatibility witness: states indistinguishable under the current frozen verifier can differ sharply in whether they propagate through a later repository transition. It does not yet establish a heldout autonomous-agent continuation gap. Counterfactual transport failure is an integration-cost event and a prerequisite failure for the planned future-agent evaluation; it should not be relabeled as future-task failure. The valid conclusion is therefore narrower: current success does not guarantee counterfactual state transportability, and this loss is concentrated in implementation files rather than patch size or documentation artifacts.

## Reproducibility

- Candidate freeze: `prospective_rsd_v3/continuation_freeze/freeze_manifest.json`
- Frozen candidate list: `prospective_rsd_v3/continuation_freeze/unique_candidates.jsonl`
- Executor amendments: `audit_executor_amendment_1.json`, `audit_executor_amendment_2.json`
- Machine-readable release summary: `real_repo_summaries/prospective_same_producer_audit.json`
- Full local audit summary: `prospective_rsd_v3/continuation_freeze/audit_results_summary.json`
- Summary script: `summarize_prospective_audit.py`
- Raw calibration and deterministic-audit file hashes are recorded in the machine-readable summary.
