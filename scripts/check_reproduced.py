#!/usr/bin/env python3
"""Compare independently regenerated quantities with frozen scientific results."""
import json, hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[1]
def load(p):return json.loads((R/p).read_text())
a=load('reproduced_outputs/continuation_selection.json')
b=load('prospective_rsd_v3/continuation_selection_analysis/analysis_yury_official.json')
assert a==b, 'Continuation reproduction differs from frozen analysis'
a=load('reproduced_outputs/sequential/sequential_selection_results.json')
b=load('prospective_rsd_v3/sequential_decision_heldout/analysis/sequential_selection_results.json')
for key in ('policies','effects'):
 assert a[key]==b[key], f'Sequential {key} differs from frozen analysis'
c=load('reproduced_outputs/selector_cost_budget.json')['sequential']
assert c['development']['attempted_transitions']==72
assert c['development']['failed_transitions']==30
assert c['development']['consumer_sessions']==42
assert c['development']['tool_calls']==708
assert all(r['heldout_success']==0.375 for r in c['budget_ablations'])
print('REGENERATED_RESULTS_MATCH_FROZEN_AND_COST_AUDIT_OK')
