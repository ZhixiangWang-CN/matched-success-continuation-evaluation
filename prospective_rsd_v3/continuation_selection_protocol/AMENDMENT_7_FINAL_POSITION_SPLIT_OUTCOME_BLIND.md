# Amendment 7: Final exact-position split (outcome-blind)

Timestamp: 2026-09-11T05:57Z

At 381/384 raw rows, the last three expected keys were queued serially in the
same shard-3 resume worker. Without inspecting outcomes, we stopped that worker
and launched exact original-position workers for positions 41, 44, and 47 using
`--num-workers 48`. Position 41 completed during shutdown and is therefore
skipped by its new worker through `--completed-from`; positions 44 and 47 remain
assigned one per GPU. Original-position seeding is unchanged.

The final audit must still require exactly 384 unique expected keys, zero seed
mismatches, and successful exit markers for all workers that actually had
pending work.
