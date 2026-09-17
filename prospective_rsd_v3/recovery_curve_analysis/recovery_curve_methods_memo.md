# Repository-cluster recovery-curve analysis

Protocol `409635ca6866dc49501c63f4ff2e310e10f5084ef6362db844b1c755db2fc6a4` was validated against all four final JSONL files. Each consumer has 624 unique raw rows. Exactly 26 rows from the same two Woodwork arms were excluded because the frozen Git reference was absent from the container image; the analysis therefore contains 598 rows, 46 complete arms, and eight repositories per consumer.

## Primary analysis

The `verified_recovery` field is analyzed as a certifiable-recovery lower bound; `replay_success` is the behavioral-preservation upper bound here because every transported prior-task verifier that actually ran passed. A false `verified_recovery` after completed replay therefore denotes verifier unavailability, not an observed behavioral failure. Independent repeats are averaged within each state--future arm, and the frozen estimand is the fraction of arms. Confidence intervals use 100,000 stratified repository-cluster bootstrap samples (five legacy and three outcome-unopened repositories sampled with replacement within stratum); each draw pools all arms in the sampled clusters and divides by their sampled arm count. Simultaneous bands use the bootstrap maximum absolute deviation across the five frozen budgets. B=3 comparisons use exact sign-flip randomization of whole repository clusters, weighted by their retained arm counts.

- Claude certifiable-recovery lower bound: B0 30.43% (pointwise 95% CI 4.17%--62.50%), B1 43.48% (pointwise 95% CI 13.04%--75.00%), B3 43.48% (pointwise 95% CI 13.04%--75.00%), B6 43.48% (pointwise 95% CI 13.04%--75.00%), B10 43.48% (pointwise 95% CI 13.04%--75.00%).
- Claude confirmatory B3-B0 arm-fraction difference: 13.04%; exact two-sided p=1.0000, directional p=0.5000 (1 positive, 0 negative, 7 ties).
- Codex certifiable-recovery lower bound: B0 30.43% (pointwise 95% CI 4.17%--62.50%), B1 44.93% (pointwise 95% CI 15.15%--78.26%), B3 54.35% (pointwise 95% CI 23.91%--83.33%), B6 56.52% (pointwise 95% CI 26.09%--87.50%), B10 56.52% (pointwise 95% CI 26.09%--87.50%).
- Codex confirmatory B3-B0 arm-fraction difference: 23.91%; exact two-sided p=0.5000, directional p=0.2500 (2 positive, 0 negative, 6 ties).
- At B3, the paired Codex-minus-Claude certifiability difference is 10.87%; exact two-sided p=1.0000 (1 positive, 0 negative, and 7 tied repositories).

## Sensitivity and limitations

Repository-macro and raw-row summaries are included only as sensitivity analyses; raw rows are not independent. With only eight selected repository clusters, cluster intervals are necessarily wide and the exact tests have coarse resolution. Certifiability improvements are concentrated in Kinto and, for Codex beyond B1, ResearchObject; no broad cross-repository or population-prevalence claim is supported. Across completed replays, verifier transport is unavailable in 33 Claude and 142 Codex rows; among the 254 and 307 rows where it runs, respectively, there are zero test failures. The two structurally unavailable Woodwork arms are excluded symmetrically for both consumers and every budget rather than counted as task failures.

Realized cost is averaged over every retained row, including failed attempts. A recovery session may contain many tool calls, so the allocated session budget is not a normalized compute budget; `recovery_curve_cost.csv` reports mean sessions, tool calls, and recovery seconds at each budget.

All generated values are reproducible by running `python3 recovery_curve_cluster_analysis.py` from this directory.
