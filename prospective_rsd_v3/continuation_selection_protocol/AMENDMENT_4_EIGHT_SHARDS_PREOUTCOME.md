# Amendment 4: Eight-way BF16 Execution (Outcome-blind)

Timestamp: 2026-09-11T05:19Z

After Amendment 3 and before launching any BF16 rollout, the user explicitly
requested additional acceleration. The official run is therefore split across
all eight idle A100-80GB GPUs on yury rather than four. Each independently
loaded BF16 model executes one deterministic modulo shard (48 of 384 keys).

This is an operational parallelization change only. The model, precision,
prompts, frozen states, selectors, held-out futures, three repeats, base seeds,
sampling parameters, batch size, executable tests, estimands, and claim gate
are unchanged. No BF16 scientific outcome existed when this amendment was
made. All eight shards must come from this single runtime and jointly contain
exactly the 384 expected unique keys before analysis.
