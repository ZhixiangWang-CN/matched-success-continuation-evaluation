.PHONY: verify reproduce

verify:
	python3 scripts/verify_release.py
	python3 scripts/reproduce_headline_results.py

reproduce: verify
	mkdir -p reproduced_outputs
	python3 prospective_rsd_v3/continuation_selection_scripts/analyze_continuation_selection_v1.py \
		--protocol-dir prospective_rsd_v3/continuation_selection_protocol \
		--results prospective_rsd_v3/continuation_selection_raw/*.jsonl \
		--output reproduced_outputs/continuation_selection.json
