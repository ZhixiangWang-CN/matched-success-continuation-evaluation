# Amendment 3: BF16 Consumer Runtime (Outcome-blind)

Timestamp: 2026-09-11T05:16Z

The complete yury panel was initially launched with bitsandbytes int8, matching
the first operational plan. After checkpoint loading, the first completed row
required 145.5 seconds for 208 tokens (1.43 tokens/s). This timing implied that
the frozen 384-rollout panel could take many hours because some completions use
the 900-token cap.

Before inspecting any `future_success`, `current_preserved`, generated code, or
other scientific outcome, we stopped this run after three rows and quarantined
all of its outputs. The only row fields inspected were `generation_s` and
`completion_tokens`. No quarantined int8 row will enter any analysis.

The official consumer precision is amended to bfloat16 on one A100-80GB per
shard. The model identity, Transformers version, prompts, frozen states,
selectors, held-out futures, seeds, sampling parameters, batch size, sharding,
tests, estimands, and claim gate remain unchanged. A100-80GB can hold the full
30B-parameter model in bfloat16, avoiding the slow bitsandbytes MoE path. The
protocol and code hashes are re-frozen before the BF16 launch.
