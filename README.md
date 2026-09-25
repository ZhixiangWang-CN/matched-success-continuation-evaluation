# Matched-Success Continuation Evaluation

This repository contains the code, frozen protocols, raw outcome rows, and
analysis artifacts for **When Success Is a Lossy Record: Matched-Success
Continuation Evaluation for Persistent Agents**.

The central evaluation unit is a pair of environment states that both pass the
same current-task verifier. We then hold the future task bank, executor,
verifier, and budget fixed and compare what can still be accomplished from each
state. This separates immediate task success from downstream continuation value.

## Evidence at a glance

| Panel | Scale | Role |
|---|---:|---|
| Controlled matched-success evaluation | 600 pairs; 1,200 continuation outcomes | Establishes that a shared current verdict can hide different futures |
| Natural-state evaluation | 64 deduplicated successful states; 936 recorded successor rollouts | Tests the effect under model-produced states |
| Frozen repository decision panel | 18 repositories; 144 heldout executions | Tests whether continuation information changes a decision |
| Independent-budget recovery | 1,196 retained evaluations; 46 arms per consumer | Measures preservation under fixed recovery budgets |
| Matched recovery/control panel | 856 consumer-matched rows | Separates candidate cost from historical control cost |
| Common-snapshot panel | 90 sessions; 5 repositories; 2 executors | Removes history-replay asymmetry |

These are execution and outcome counts, not interchangeable independent sample
sizes. Statistical inference uses the model, state, family, or repository unit
appropriate to each frozen panel.

## What is included

- `empirical_results/`: controlled and natural-state outcome rows and frozen summaries.
- `analysis/`: analysis code for the controlled and natural-state studies.
- `prospective_rsd_v3/`: frozen repository protocols, raw rollouts, recovery
  curves, common-snapshot panels, continuation-selection experiments, and their
  analysis code.
- `claim_evidence_ledger.md`: claim-to-artifact map and warnings for superseded analyses.
- `MANIFEST.txt` and `SHA256SUMS.txt`: the release inventory and integrity checksums.
- `REPRODUCIBILITY.md`: exact verification levels and commands.

Repository checkouts, model weights, proprietary model services, and container
images are not redistributed. The stored outcome rows and analysis scripts are
sufficient to verify the reported aggregates without rerunning model inference.

## Quick start

Python 3.10 or newer is recommended.

Download the frozen anonymous snapshot and unpack it:

```bash
curl -L \
  https://anonymous.4open.science/api/repo/matched-success-continuation-evaluation-B117/zip \
  -o matched-success-continuation-evaluation-B117.zip
unzip matched-success-continuation-evaluation-B117.zip
cd matched-success-continuation-evaluation-B117
```

The Anonymous GitHub mirror is a frozen review snapshot rather than a Git remote,
so it should be downloaded as a ZIP instead of cloned with `git clone`.

Create the verification environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
make verify
```

`make verify` performs a release-integrity scan and independently checks the
headline values used in the paper. It does not call a model API, download a
model, or launch a container. Run `make reproduce` for the slower frozen-data
analyses.

## Evidence tiers

| Tier | Available here | External requirements |
|---|---|---|
| Frozen-result verification | Yes | Python standard library |
| Statistical re-analysis | Yes | NumPy, SciPy, scikit-learn, Matplotlib |
| Repository replay | Harness and protocols | Upstream snapshots and container runtime |
| New agent rollouts | Harness and protocols | Matching model/API access and compute |

The frozen JSON summaries are authoritative for manuscript values. Files marked
as interim, pilot, quarantined, or superseded are retained for provenance and
must not replace the final analyses identified in `claim_evidence_ledger.md`.

## Scope

The release supports a measurement claim: current-task success does not uniquely
determine downstream value under a specified continuation context. It does not
establish a universal ranking of states, a deployment-wide prevalence estimate,
or a model-independent state-quality score.

## License

Original analysis and orchestration code is released under the MIT License.
Frozen benchmark records can contain issue text, patches, and metadata derived
from upstream open-source repositories and remain subject to their original
licenses; see `THIRD_PARTY_LICENSES.md`.

## Double-blind review

The repository contents and commit metadata are intentionally author-anonymous.
During double-blind review, cite only the anonymous mirror supplied in the
manuscript. The canonical GitHub URL should be used after de-anonymization.
