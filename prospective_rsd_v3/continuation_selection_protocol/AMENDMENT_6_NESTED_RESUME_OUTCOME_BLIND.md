# Amendment 6: Nested resume of the remaining shard-4 keys (outcome-blind)

Timestamp: 2026-09-11T05:53Z

After the first resume split, the shard-4 even-position worker had completed
only 1/12 assigned rows while four GPUs had become idle. Without inspecting any
scientific outcome, we stopped that worker and reassigned its 11 unfinished
original positions to four workers selected by position modulo 8 (residues
0, 2, 4, and 6). The original shard file and both first-level resume files are
provided through `--completed-from`, so already completed keys are skipped.

This uses the runner frozen in Amendment 5. Seeds remain functions of the
original shard position, not the resume worker or local loop index. The final
coverage audit must combine every original and resume result file and reject
duplicates, missing keys, extra keys, or seed mismatches before outcomes are
opened.
