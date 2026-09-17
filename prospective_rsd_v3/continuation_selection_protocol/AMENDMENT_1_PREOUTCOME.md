# Amendment 1, pre-outcome task-interface correction

Timestamp: 2026-09-11T04:16:32Z

The initial `cache/update_many` hidden test called `contains("c")`, although the independent `update_many` prompt did not request a `contains` method. This would confound compliance with an unspecified interface. Four model processes had begun loading, but the remote quarantine receipt confirms that zero outcome rows existed when they were stopped.

Before any held-out outcome was generated, the `update_many` test was changed to store an ordinary numeric value for the new key and verify it using the already specified `get` method. No selector, candidate state, other future, model, repeat count, endpoint, estimand, inference procedure, or claim gate changed. The protocol and all task and code hashes are regenerated after this amendment.

Remote quarantine: `continuation_selection_v1/quarantine_pre_amendment_contains_dependency_20260911T041632Z`

Rows before amendment: 0
