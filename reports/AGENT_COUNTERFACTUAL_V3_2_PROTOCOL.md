# Agent Counterfactual V3.2: Same-Producer Diversity Rescue

## Status

This adaptive protocol was frozen after V3.1 completed with a no-go and before V3.2 was launched or produced outputs.

## Diagnosed failure being targeted

All four V3.1 dataclasses-jsonschema candidate trajectories ended at the unchanged historical reference state (`e504347a…`). The model repeatedly attempted to apply hunks from a reference diff that was already present. Consequently, no automatic candidate validation was triggered for that anchor.

V3.2 tests a narrow controller hypothesis: candidate diversity may become feasible if the prompt unambiguously marks the reference diff as already applied and the controller counts an edit only after the Git tree actually changes.

## Fixed design

- Model: Qwen2.5-72B-Instruct for every trajectory (same producer)
- Anchor: dataclasses-jsonschema only
- Two independent seed blocks, 8 trajectories each (16 total)
- Eight fixed design strategies per block
- Temperature 0.4, 12 action steps, at most three pre-edit shell actions
- Same network isolation, current-task oracle, regression subset, artifact cleanup, and clean replay gates as V3.1
- Diversity is computed from the successful post-reference alternative delta; full serialized patch hashes are also retained

## Frozen go/no-go gate

V3.2 is a **GO** only if all conditions hold:

1. at least 4 of 16 trajectories pass all current-task gates after clean replay;
2. at least 3 unique successful alternative-delta hashes are present;
3. each independent seed block contributes at least one successful candidate.

A go permits combining these dataclasses states with the two successful Qwen-produced Werkzeug states from V3.1 for same-producer continuation and probe scoring. A no-go means the free-form LLM counterfactual generator remains the bottleneck and should be replaced by constrained program transformation or search, not scaled unchanged.
