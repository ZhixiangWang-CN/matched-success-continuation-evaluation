# Task-instance-disjoint confirmatory result

## Frozen design

No discovery task instance appears in this split. The unchanged high-precision repayment rule identifies nine
candidates in nine distinct repositories, and every candidate is executed without manual outcome filtering.

## Result

3/9 frozen candidates are direct continuation
wins (rate 33.3%, Wilson 95% CI 12.1%–64.6%). Among the
5 candidates satisfying all current-task gates, the rate is
60.0% (Wilson 95% CI 23.1%–88.2%).

| Repository | Category | Continuation (debt→clean) | Remaining patch lines | Remaining churn |
|---|---|---:|---:|---:|
| alteryx/woodwork | incompatible_or_invalid_clean | 0 → 0 | 195 → 119 | 58 → 22 |
| d0c-s4vage/pfp | direct_continuation_win | 0 → 1 | 42 → 0 | 22 → 0 |
| PyCQA/docformatter | direct_continuation_win | 0 → 1 | 16 → 0 | 5 → 0 |
| reata/sqllineage | compatible_partial_repayment | 0 → 0 | 45 → 30 | 16 → 12 |
| tornadoweb/tornado | incompatible_or_invalid_clean | 0 → 1 | 165 → 44 | 70 → 16 |
| pyccel/pyccel | compatible_partial_repayment | 0 → 0 | 87 → 52 | 29 → 12 |
| s-knibbs/dataclasses-jsonschema | direct_continuation_win | 0 → 1 | 30 → 0 | 14 → 0 |
| PyCQA/pyflakes | incompatible_or_invalid_clean | 0 → 1 | 320 → 25 | 176 → 3 |
| neogeny/TatSu | incompatible_or_invalid_clean | 0 → 1 | 111 → 55 | 37 → 13 |

Across matched-current candidates, remaining patch size is **220 → 82**
(-62.7%) and source churn is **86 → 24**
(-72.1%).

This is a task-instance-disjoint confirmation, not a strict repository-heldout confirmation; repositories may
recur between discovery and confirmation. A separate repository-heldout audit had zero coverage under the exact
same-file repayment rule and is reported as a coverage limitation rather than a negative outcome.
