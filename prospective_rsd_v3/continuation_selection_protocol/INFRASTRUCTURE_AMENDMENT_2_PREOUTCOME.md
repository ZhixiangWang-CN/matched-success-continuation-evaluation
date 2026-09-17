# Infrastructure Amendment 2 (Pre-outcome)

Timestamp: 2026-09-11T04:50Z

The initial nugpu launch attempted four independently loaded bitsandbytes-int8
instances of Qwen3-Coder-30B-A3B-Instruct. Three instances consumed about 90%
of host RAM; shard 2 was killed during checkpoint loading with exit code 137
and wrote zero result rows. The surviving shards later wrote one row each.

Before inspecting any `future_success`, `current_preserved`, generated code, or
other scientific outcome, we inspected only process liveness, row counts,
checkpoint-loading progress, GPU/host utilization, and the `generation_s`
field of the first completed rows. We then designated a complete four-shard
run on yury as the sole official panel. Yury had eight idle A100-80GB GPUs and
an existing cache of the identical model. The scientific protocol remains
unchanged: the same frozen states, selectors, hidden futures, seeds, int8
precision, batch size 1, and four-way deterministic sharding are used.

No nugpu result row will be combined with the yury panel or used in the primary
or secondary analyses. Nugpu files are retained only as infrastructure records.
The official panel must contain exactly 384 unique expected keys, all from the
single yury runtime, before outcomes are analyzed.
