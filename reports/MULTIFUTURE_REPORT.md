# Real multi-future sequence construction

## Question

Can residual-state debt be evaluated against a distribution of real later tasks, rather than a single selected
successor issue?

## Frozen selection

The selector streams all 6,272 tasks in `PrimeIntellect/SWE-rebench-V2-Filtered-Verified`, retains executable
Python tasks under the same 240-line patch limits as the pair study, and searches for an anchor followed by three
to five temporally ordered tasks connected through shared implementation files. Selection requires at least two
future tasks to overlap the anchor directly. It found 437 candidate sequences and retained one sequence from each
of 50 repositories (233 anchor-to-future pairs total).

## Historical validity

Each anchor-to-future pair is independently checked for non-duplication, commit ancestry, and survival of at least
half of the substantive anchor-patch additions at the future base commit.

| Valid future tasks per sequence | Sequences |
|---:|---:|
| 0 | 3 |
| 1 | 5 |
| 2 | 2 |
| 3 | 6 |
| 4 | 10 |
| 5 | 24 |

Thirty-one of 50 sequences pass every future-task validity gate, and 40 of 50 contain at least three valid future
tasks. Among the all-valid sequences, the median of each sequence's minimum patch-survival rate is 0.864. This
provides a repository-diverse pool for estimating a continuation-value distribution and its variance across future
task families.

## What this does and does not establish

This result establishes coverage and historical validity, not a debt effect. The next execution stage must create
matched historical and clean states at each anchor, run every valid future task independently from both states,
and report mean continuation success, worst-case continuation success, recovery cost, and between-future
variance. Unrelated future tasks from the same repositories should be sampled as a negative control.

A stricter follow-up centered on the existing direct-debt anchors finds 18 valid futures across five anchors. After
requiring that the clean delta be constructible at the anchor and propagatable to the future base, three anchors
and eight future tasks remain. Three natural repayment futures show clean-only success and reduced recovery cost;
five other related futures are exact cost ties. See `DIRECT_MULTIFUTURE_REPORT.md`.

## Frozen artifacts

- `sequences.jsonl`: `a748b2320b78add304548d3b8d9ad46945486098e08289fede7a76942c477f8c`
- `pairs.jsonl`: `2f8018a17f29deb7981ffae91fb4aa86ea4b8af7e79e0b996449285e1be2cadf`
- `validation.jsonl`: `1fb789c484b41ccf11d1ccf6fc0cc6e5cc3a5e55011f1196662c1f9bf6ee056c`
- `summary.json`: `69fe2f1bac762c809d5b8bcf5700fc47e94c8a3b9d2b0030f6b1986f7a3a0601`
