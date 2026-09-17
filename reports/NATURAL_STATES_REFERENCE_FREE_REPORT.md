# Reference-Free Natural-State Heterogeneity Analysis

## Design

For each source state, the uniform mean successor success over the fixed consumer x future-task bank; repeated generations of an identical source within a cell are averaged before cells are uniformly weighted.

The best observed state is never used as a reference. Within each family x consumer x future stratum, repeat-averaged state-cell values are exchangeable across source states. A secondary sensitivity analysis instead shuffles binary generation slots and assumes within-cell repeats are independent.

## Global result

- Pooled within-family observed state-value variance: 0.015469.
- Randomization-null mean variance: 0.008984 (95% interval 0.006038--0.012435).
- Noise-corrected excess variance: 0.006485; upper-tail randomization p=0.00049995.
- Observed mean pairwise absolute gap: 0.1292; null mean 0.1019; corrected gap 0.0273; p=0.00229977.
- Binary-slot sensitivity (requires independent repeats): corrected variance 0.007248, p=9.999e-05; corrected pairwise gap 0.0324, p=0.00069993.

## Family-level results

| Family | States | Obs. variance | Null variance | Corrected | p | Holm p | Obs. pairwise gap | Corrected gap | p | Holm p | Future-split rho | Consumer rho |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cache | 9 | 0.00868 | 0.00519 | 0.00349 | 0.0721 | 0.3605 | 0.102 | 0.025 | 0.1217 | 0.6084 | 0.266198568749975 | NA |
| events | 13 | 0.03708 | 0.01438 | 0.02270 | 0.0007 | 0.0042 | 0.217 | 0.083 | 0.0017 | 0.0102 | 0.39757960122890246 | 0.5055458036086481 |
| flags | 8 | 0.00865 | 0.00828 | 0.00037 | 0.4688 | 0.9375 | 0.106 | 0.005 | 0.4350 | 1.0000 | -0.6829877767625105 | 0.2927700218845599 |
| permissions | 15 | 0.01534 | 0.01104 | 0.00431 | 0.1614 | 0.6455 | 0.143 | 0.027 | 0.1240 | 0.6084 | 0.21721803209997953 | 0.2810813654562216 |
| pricing | 12 | 0.00773 | 0.00620 | 0.00153 | 0.3123 | 0.9368 | 0.087 | 0.002 | 0.4685 | 1.0000 | -0.13554750160481385 | 0.49236596391733095 |
| router | 7 | 0.00372 | 0.00438 | -0.00066 | 0.5720 | 0.9375 | 0.071 | -0.004 | 0.5954 | 1.0000 | 0.02021130208636108 | NA |

## Interpretation boundary

This analysis can support a claim of reference-free heterogeneity only when the randomization-calibrated dispersion exceeds the null. It cannot turn the observed family maximum into a clean counterfactual, assign signed debt to states, or estimate deployment prevalence. Future-split and cross-consumer correlations diagnose whether a single state ranking is stable; low correlations imply executor/task dependence.

## What is not identified

- A clean or oracle state, or signed residual-state debt for any individual state.
- The prevalence or expected magnitude of debt in a deployment population; producer attempts and task families were selected.
- Continuation value under unseen future-task distributions or unseen executors.
- A causal effect of naturally generated state structure; state content is observational and may be confounded with producer and generation seed.
- Reliable state rankings when split-half or cross-consumer agreement is weak.
