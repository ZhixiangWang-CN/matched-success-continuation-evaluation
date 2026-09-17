# Task-Conditioned State-Debt Kernel: Pilot Report

## Question

Can a critic predict which successful residual state will preserve more value for a particular future task, rather than merely learning that some tasks are easier than others?

A deployable state-debt critic must support **within-task state selection**: for the same continuation task, it should rank candidate terminal states by their eventual continuation outcome.

## Setup

- 768 state–task observations
- 64 unique residual states
- 72 task–consumer selection groups
- Evaluation 1: known task distribution, held-out states
- Evaluation 2: held-out task families
- Models: state-only, task-only, additive state–task context, conditional kernel, pairwise conditional objective, producer-context controls, and producer-adjusted conditional kernels
- Primary decision metric: outcome of the state selected within each fixed task–consumer group
- Selection comparisons are fold-consistent: states are ranked only when their scores were produced by the same fitted cross-validation model; fold-level outcomes are then averaged within each of the 72 task–consumer clusters.

The executable experiment and full machine-readable output are in `task_conditioned_kernel_pilot.py` and `empirical_results/task_conditioned_kernel_pilot.json`.

## Results

### Pointwise prediction

| Model | Held-out-state ROC-AUC | Held-out-family ROC-AUC |
|---|---:|---:|
| State only | 0.544 | 0.360 |
| Task only | 0.891 | 0.630 |
| Additive context | **0.894** | 0.544 |
| Producer context | 0.888 | **0.689** |
| Conditional kernel | 0.873 | 0.586 |
| Conditional + producer context | 0.875 | 0.593 |
| Pairwise conditional | 0.548 | 0.524 |

The high held-out-state AUC is largely explained by task identity or task difficulty. Task-only prediction reaches 0.891 AUC and adding state features changes it only to 0.894. This metric therefore does not establish that the critic understands residual-state debt.

### Within-task state selection

| Selector | Mean continuation success | 95% bootstrap CI |
|---|---:|---:|
| State only | 0.594 | [0.499, 0.684] |
| Task only | 0.553 | [0.453, 0.649] |
| Additive context | 0.611 | [0.518, 0.699] |
| Producer context | 0.614 | [0.526, 0.697] |
| Producer-conditional context | 0.613 | [0.520, 0.699] |
| Conditional kernel | **0.632** | [0.542, 0.715] |
| Conditional + producer context | 0.617 | [0.526, 0.703] |
| Pairwise conditional | 0.589 | [0.494, 0.679] |
| Random expected | 0.587 | [0.497, 0.674] |
| Oracle | 0.694 | [0.612, 0.772] |

The conditional kernel exceeds random selection by 0.0454, with a task-clustered paired 95% CI of [0.0215, 0.0698]. The additive model's +0.0246 contrast narrowly includes zero, [-0.0007, 0.0497], and the state-only model is indistinguishable from random. Thus, the interaction between state and future-task context—not a generic state-quality score—carries the useful selection signal.

The pairwise conditional objective does not help: it exceeds random by only 0.0024, CI [-0.0251, 0.0303], and underperforms the pointwise conditional kernel by 0.0431, CI [-0.0694, -0.0174].

### Producer-confound stress test

The unadjusted positive association does **not** isolate residual-state quality. A task/consumer/producer baseline, with no state-structure features, already exceeds random by +0.0274, CI [0.0036, 0.0514]. Adding state features to that baseline improves selection by only +0.0056, CI [-0.0243, 0.0361]. With task–producer and consumer–producer interactions, the incremental state-feature gain is +0.0049, CI [-0.0250, 0.0354]. The fully producer-adjusted conditional selector remains above random (+0.0308, CI [0.0062, 0.0554]) but is worse than the unadjusted conditional kernel by -0.0146, CI [-0.0285, -0.0028].

A stricter choice-set restriction holds producer identity fixed and asks the critic to choose only among different states produced by the same model. Across 360 task–consumer–producer groups, the conditional kernel is slightly below random: -0.0028, CI [-0.0125, 0.0069]. Restricting to 144 fold groups with at least two candidate states gives +0.0069, CI [-0.0313, 0.0451]. Even among the 30 diagnostic groups with discordant outcomes, the estimate is +0.0333 with a wide CI [-0.1333, 0.2000]. Family-level sign-flip `p` is 0.75.

When entire producer groups are held out during training, the conditional model still has high pointwise AUC (0.889), again largely because it predicts task difficulty. Its within-producer selection gain is +0.0181, CI [-0.0023, 0.0380]; among choice sets with at least two states it is +0.0246, CI [-0.0032, 0.0524]. The family-level sign-flip value is 0.5625. This is a suggestive trend, not resolved evidence of producer-independent state ranking.

This is the decisive negative result: the current data support a producer-associated selection signal, but not a learned ability to distinguish higher- and lower-debt states from the same producer.

### Concentration audit

The conditional-kernel gain over random is positive for all three downstream agent consumers:

| Consumer | Gain over random | 95% cluster-bootstrap CI |
|---|---:|---:|
| Llama-3 8B | +0.0533 | [0.0023, 0.1017] |
| Qwen2.5 7B | +0.0434 | [0.0045, 0.0891] |
| Qwen2.5 72B | +0.0396 | [0.0120, 0.0720] |

The gain is not uniform across task families. It is largest for `events` (+0.1056, CI [0.0417, 0.1694]) and `permissions` (+0.0920, CI [-0.0035, 0.1789]); the other four families have small positive point estimates whose 12-group intervals include zero. Thus the aggregate effect is not a single-consumer artifact, but broader task-family coverage remains an explicit scaling target.

Treating the six task families—not the 72 task–consumer groups—as the independent units gives an exact two-sided family-level sign-flip value of 0.03125. All six family point estimates are positive, and leave-one-family-out aggregate gains range from +0.0334 to +0.0520. This stricter audit reduces the pseudo-replication concern, although six families remain too few for a broad universality claim.

### Split and regularization sensitivity

A separate robustness sweep evaluated 20 randomized state-level five-fold partitions at six logistic-regularization values (`C` = 0.03, 0.1, 0.3, 1, 3, 10), for 120 fold-consistent selection trials. The conditional kernel beat random in all 120 configurations. Mean gain was +0.0326 (standard deviation 0.0105; range +0.0011 to +0.0555). Mean gains by `C` ranged from +0.0271 to +0.0354, and every `C` had a 100% positive split fraction.

This removes the concern that the aggregate positive result depends on one fortunate state partition or a single regularization choice. The executable sweep is in `task_conditioned_kernel_robustness.py`, with results in `empirical_results/task_conditioned_kernel_robustness.json`.

### State-feature permutation control

A 500-draw state-level permutation test shuffled complete feature vectors among state identities while preserving future tasks, consumers, labels, and cross-validation folds. The null mean selection gain was +0.0014, with a 95% null interval of [-0.0292, 0.0350]. The observed +0.0454 gain exceeded 498 of 500 shuffled draws (add-one one-sided `p = 0.0060`). Thus the unadjusted result depends on the state-feature/outcome mapping rather than only task difficulty or generic selector bias. The producer audit shows that this permutation result is not sufficient evidence for state-specific debt prediction, because structural features can encode producer identity.

The executable control and all null draws are in `task_conditioned_kernel_permutation.py` and `empirical_results/task_conditioned_kernel_permutation.json`.

## Conclusion

This pilot gives a **positive unadjusted association but a negative result for the current state-specific critic claim**. A conditional state–task model selects better than random when states from all producers compete, but the advantage disappears when producer identity is controlled or held fixed. Ordinary pointwise AUC substantially overstates progress, and even a permutation-significant selection result can remain confounded by who generated the state.

The primary critic claim should therefore require all of the following:

1. Evaluation groups must hold the continuation task fixed while varying residual state.
2. State selection regret or continuation success must be primary; global AUC is diagnostic only.
3. Confidence intervals must be computed over task–consumer groups, not individual rows.
4. A task-only baseline is mandatory to expose task-difficulty leakage.
5. Producer-only and within-producer baselines are mandatory to expose model-identity leakage.
6. Training data need substantially more counterfactual state variation from the **same producer** for each identical future task.

The unrestricted oracle gap (0.694 versus 0.587 random) confirms that meaningful state choice exists, but it mixes state quality with producer quality. Within producer, groups containing at least two candidates retain an oracle gap of about 0.104 (0.646 versus 0.542), yet the critic closes only 0.007 of it with an unresolved interval. The next experiment must create balanced, same-producer counterfactual states and train/evaluate entirely within those matched choice sets.
