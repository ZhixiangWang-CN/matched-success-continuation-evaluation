# Earlier-state prediction pilot

## Question

Can future natural repayment be predicted using only information available immediately after the earlier task?
The audited corpus contains 148 temporal pairs from distinct repositories. Nineteen are positive under the
current high-precision label: the later maintainer patch substantively removes or replaces code added by the
earlier patch.

## Out-of-fold result

All metrics use five-fold stratified out-of-fold predictions. The permutation test repeats the complete
classifier fitting procedure 500 times.

| Earlier-state features | Average precision | ROC-AUC | Precision@19 | Permutation p (AP) |
|---|---:|---:|---:|---:|
| Patch size/shape only | 0.293 | 0.693 | 0.316 | 0.012 |
| Earlier issue + added-code text only | 0.204 | 0.588 | 0.105 | 0.114 |
| Combined | 0.275 | 0.695 | 0.316 | 0.012 |

The positive prevalence—and hence random-ranking AP—is 0.128. There is prospective signal, but it is carried
mainly by patch exposure and structural size. Text does not improve over the simple baseline.

## Strong-case audit

The combined baseline ranks the nine confirmed direct-continuation events at 8 (Botocore), 17 (PyBaMM),
18 (APIFlask), 28 (Sanic-ext), 37 (Dynaconf), 67 (Werkzeug), 84 (Laspy), 87 (PyDriller), and 119
(Flake8-comprehensions) out of 148. Only three enter the top-19 selection budget. Thus this baseline does not
reliably recover the most causally convincing debt events even though its aggregate AP is above chance.

## Task-instance-disjoint confirmation

The frozen models are then trained on all 148 discovery episodes and evaluated once on 73 valid episodes that
reuse none of the 400 discovery task instances. Nine test episodes contain later natural repayment.

| Earlier-state features | Held-out AP | Held-out ROC-AUC | Precision@9 | Label-permutation p |
|---|---:|---:|---:|---:|
| Patch size/shape only | 0.339 | 0.673 | 0.222 | 0.027 |
| Earlier issue + added-code text only | 0.118 | 0.397 | 0.111 | 0.799 |
| Combined | 0.304 | 0.647 | 0.222 | 0.044 |

Held-out prevalence is 0.123. The prospective size/shape signal replicates, while the text representation fails
and reduces performance when combined with size. Task instances are disjoint, although some repositories recur.

## Frozen large-model representation control

A Qwen2.5-14B last-token representation is extracted from the earlier issue and added code only, then a fixed
linear classifier (`C=0.1`) is trained on discovery and evaluated on the same confirmatory split. Embedding-only
performance is AP 0.130 and ROC-AUC 0.480 (label-permutation p=0.678). Adding the size features yields AP 0.131
and ROC-AUC 0.485 (p=0.682). Thus a larger generic semantic representation does not recover the held-out signal
and can suppress the strong size baseline. This is a control against the claim that debt prediction is solved by
off-the-shelf language-model embeddings.

## Interpretation

This is useful in two ways. First, future repayment is not wholly unpredictable at task completion. Second, any
proposed state-debt critic must beat a strong patch-size baseline and demonstrate added value on direct
continuation failures, not merely on the lexical-repayment label.

The label remains positive-unlabeled: absence of exact later code removal does not prove absence of debt.
Confirmatory evaluation requires more executable direct events and a held-out corpus selected before model
development.
