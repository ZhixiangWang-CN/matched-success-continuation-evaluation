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
	python3 prospective_rsd_v3/sequential_decision_heldout/scripts/analyze_sequential_decision_heldout_v1c.py \
		--results prospective_rsd_v3/sequential_decision_heldout/raw_results/*.jsonl \
		--selection prospective_rsd_v3/sequential_decision_heldout/selection_ledger.json \
		--protocol prospective_rsd_v3/sequential_decision_heldout/protocol.json \
		--output-dir reproduced_outputs/sequential
	python3 scripts/selector_cost_budget.py
	python3 scripts/check_reproduced.py
