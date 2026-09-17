# Multi-future effects from executable debt anchors

## Strict design

The 14 direct-effect candidates are used as anchors and matched against every later verified Python task that
touches an anchor-relevant file. Five confirmatory anchors yield 18 historically valid future tasks. A clean state
is admitted only if its delta can first be constructed on the solved anchor tree and then propagated to a future
base. This audit excludes Tornado and Pyflakes because their future-base prepayment cannot be constructed at the
anchor boundary; it also excludes any individual future base where the normalized delta is incompatible.

The strict executable set contains three anchors (pfp, docformatter, and dataclasses-jsonschema) and eight matched
future tasks.

## Continuation success

| Outcome across eight matched future tasks | Count |
|---|---:|
| Clean succeeds, debt fails | 3 |
| Debt succeeds, clean fails | 0 |
| Both succeed | 0 |
| Both fail | 5 |

The three clean-only wins are exactly the natural repayment tasks that identified each debt mechanism. The five
other file-related futures fail from both states. The one-sided exact sign test is p=0.125.

## Merge-aware recovery cost

The real future maintainer patch is merged independently onto each state, and the semantic diff from the starting
state to that merge target is measured.

- Three repayment futures have positive recovery-cost reductions; five other related futures are exact ties.
- No future task is more expensive from the clean state.
- Aggregate remaining patch size is 365→277 lines (-24.1%).
- Aggregate source churn is 160→119 (-25.6%).
- The directional sign test over non-ties is p=0.125.

## Interpretation

Residual-state debt is not a uniform penalty on every later task in the same repository or file neighborhood. Its
effect is sparse and structure-dependent: it materializes when a future task traverses the polluted abstraction,
interface, or dependency, while nearby tasks can be exact ties. A benchmark therefore needs a future-task
distribution with both mechanism-related tasks and unrelated controls, and should report conditional continuation
value rather than only an unconditional average.

The sample is still small (three strict anchors), so this establishes the shape of the estimand rather than a
population effect size.
