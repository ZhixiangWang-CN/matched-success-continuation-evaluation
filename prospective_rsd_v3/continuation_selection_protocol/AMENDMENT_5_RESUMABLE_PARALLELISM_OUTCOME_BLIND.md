# Amendment 5: Seed-preserving resumable parallelism (outcome-blind)

Timestamp: 2026-09-11T05:49Z

The eight-shard BF16 run revealed strong deterministic load imbalance because
some modulo shards contained many completions that reached the 900-token cap.
After 314/384 rows, four shards had completed while shards 2--4 remained slow.
No `future_success`, `current_preserved`, generated code, or scientific outcome
had been inspected; only row counts and timing fields were monitored.

The runner is amended to support `--completed-from`, `--worker-index`, and
`--num-workers`. Each original shard position is assigned to exactly one resume
worker. Crucially, the generation seed now uses that original shard position.
This equals the pre-amendment uninterrupted-run seed for every already completed
row and preserves the intended seed for every remaining row, independent of
resume-worker partitioning. Batch size remains one.

The partial original shard files remain official. The remaining keys from
shards 2--4 are split across eight independently loaded BF16 workers on the
same yury runtime. Analysis must combine original and resume files and reject
any duplicate, missing, or extra key before revealing outcomes.
