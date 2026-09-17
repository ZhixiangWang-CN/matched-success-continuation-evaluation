# Protocol 28 completion receipt

- Status: COMPLETE_AND_VALIDATED
- Consumer: Codex CLI `gpt-5.6-terra`, medium reasoning, ephemeral sessions
- Frozen protocol: `symmetric-future-terra-28`
- Required/observed unique keys: 45/45
- Shard rows: 10 + 12 + 10 + 13 = 45
- Fatal/setup failures in retained rows: 0
- Prior-task verifier preservation: 45/45
- Protocol field matches: 45/45
- Model field matches: 45/45
- Analysis bootstrap: 20,000 future-pair cluster draws, seed 280910

## Primary result

- Historical joint future success: 12/15 (80.0%)
- Candidate joint future success: 25/30 (83.3%)
- Pair-weighted candidate minus historical: +3.33 percentage points
- Repository-cluster bootstrap 95% interval: [0.0, 10.0] percentage points

## Repository structure

- Woodwork, Moto, Kinto, and Python-Markdown: every state succeeds 3/3.
- Jsonpickle: historical 0/3, s0 1/3, s1 0/3.
- The nonzero contrast is therefore confined to Jsonpickle.

## Frozen artifact SHA-256

- Protocol: `18ba1d1d6694076db1c5254f270d712315f02f20614dbb48d3e8b27558732124`
- Shard 0: `0944804c9e34f7172736f10fac6d03b3f733b51e4d2835d854cd5c8bab72f12c`
- Shard 1: `bb1230ac0a96486ddbecc04bcc3194de09eacf7ed6acb769fd9f0fa862e32a18`
- Shard 2: `48722e6d4039175484fe1aee33611108af415e4b5facdcb8ab5249bdae2f1e42`
- Shard 3: `91bf2b5b1760ca2cdb4f0d44dfde3ed818375c0a20854858b0a1f22c30486230`
- Analysis JSON: `84ca63cb63e70245c1d37e2348e85f808356949ed6c17797c77965b2dec9d124`
- Analysis script: `9db03fdad3f53ed46ee6732b4af00ed171e502d36d60afbbde6953e5893c7f7f`

## Interpretation boundary

This is a within-OpenAI-family consumer-sensitivity result. It replicates the direction and repository concentration of the Sol panel, but attenuates the aggregate effect from +10.0 to +3.33 points and changes the Jsonpickle candidate ranking. It is not a cross-vendor replication and does not enlarge repository coverage.
