# Reproducibility guide

## Level 1: integrity and headline checks

This level uses only the Python standard library and completes quickly:

```bash
python scripts/verify_release.py
python scripts/reproduce_headline_results.py
```

The first command checks the frozen supplementary checksums and scans tracked
text files for credentials and author-identifying absolute paths. The second
validates the headline quantities from the frozen analysis artifacts.

## Level 2: statistical re-analysis

```bash
python -m pip install -r requirements.txt
make reproduce
```

This re-analyzes frozen rows without inference. The recovery-curve analysis uses
100,000 repository-cluster bootstrap draws and is intentionally slower.

The frozen 18-repository decision panel can also be recomputed directly:

```bash
python prospective_rsd_v3/sequential_decision_heldout/scripts/analyze_sequential_decision_heldout_v1c.py \
  --results prospective_rsd_v3/sequential_decision_heldout/raw_results/shard0.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard1.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard2.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard3.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard4.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard5.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard6.jsonl \
            prospective_rsd_v3/sequential_decision_heldout/raw_results/shard7.jsonl \
  --selection prospective_rsd_v3/sequential_decision_heldout/selection_ledger.json \
  --protocol prospective_rsd_v3/sequential_decision_heldout/protocol.json \
  --output-dir /tmp/sequential-decision-analysis
```

## Level 3: repository replay and new rollouts

The release contains frozen protocols and orchestration code, but full replay
also requires the upstream repository states or benchmark container images.
Generating new consumer outcomes additionally requires access to the named
models or APIs. These dependencies are not silently replaced with different
models because doing so changes the continuation context and the estimand.

## Integrity rules

1. Treat files marked `final` or identified as authoritative in
   `claim_evidence_ledger.md` as manuscript inputs.
2. Retain pilot, invalidated, infrastructure-quarantined, and superseded files
   for provenance; do not pool them into the primary analysis.
3. Preserve candidate selection, future banks, executors, verifiers, and budgets
   when reproducing a frozen comparison.
4. Report missing consumer rows as missing. Do not impute them as failures.
