# Frozen held-out continuation-selection result

- Protocol: `continuation_aware_selection_v1`
- Consumer: `qwen3_coder_30b_a3b_bf16`
- Coverage: 384/384 rows,
  64 states, 6 families,
  12 held-out futures, 3 repeats
- Claim gate: **NO-GO**
- Continuation-selected held-out success: 91.67%
- Current-success random-choice expectation: 81.70%
- Primary effect: 9.97 percentage points
  (family-cluster bootstrap 95% CI [-11.10, 35.28])
- Exact one-sided random-selection p: 0.238088
  over 1,179,360 possible choices
- Shortest-state baseline: 69.44%
- Continuation-selected minus shortest: 22.22 percentage points
  (family-cluster bootstrap 95% CI [-16.67, 58.33])

The claim gate was frozen before held-out execution. The result supports a
decision-utility claim only when the primary effect is positive and the exact
one-sided random-selection p-value is below 0.05.
