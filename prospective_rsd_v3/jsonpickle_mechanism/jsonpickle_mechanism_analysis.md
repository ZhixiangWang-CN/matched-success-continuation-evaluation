# Jsonpickle source-level mechanism audit

The current task adds reference registration for plain dictionaries. The later task requires the same bookkeeping for a dictionary subclass's attribute dictionary. Successful candidate-state trajectories route `obj.__dict__` through `_flatten`, reusing the earlier primitive. Historical-state trajectories instead repeatedly modified decoder bookkeeping and did not pass the joint verifier.

| Consumer | Historical | s0 | s1 | Candidate minus historical |
|---|---:|---:|---:|---:|
| Sol | 0/3 | 1/3 | 2/3 | +50.0 pp within Jsonpickle |
| Terra | 0/3 | 1/3 | 0/3 | +16.7 pp within Jsonpickle |

Across the five frozen repositories, Jsonpickle is the sole non-zero repository effect. For each consumer, the exact two-sided sign-flip p-value over repository effects is 1.00 and the leave-Jsonpickle-out mean effect is 0. These statistics constrain the result to a mechanism case study and do not support a population-level benefit claim.
