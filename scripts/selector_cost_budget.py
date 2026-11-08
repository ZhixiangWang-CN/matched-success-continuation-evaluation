#!/usr/bin/env python3
"""Retrospective cost/subsampling audit. No new model calls or prospective claims."""
import json, hashlib, itertools, statistics, csv
from pathlib import Path
from collections import defaultdict, Counter
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT / "reproduced_outputs"
OUT.mkdir(exist_ok=True)
sources={}
def read(p):
 p=ROOT/p if isinstance(p,str) else p
 sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
 return json.loads(p.read_text())
def rows(pattern):
 out=[]
 for p in sorted(ROOT.glob(pattern)):
  sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
  out.extend(json.loads(l) for l in p.read_text().splitlines() if l.strip())
 return out
mean=statistics.mean
D=rows('prospective_rsd_v3/sequential_decision_development/raw_results/*.jsonl')
H=rows('prospective_rsd_v3/sequential_decision_heldout/raw_results/*.jsonl')
L=read('prospective_rsd_v3/sequential_decision_heldout/selection_ledger.json')['repositories']
assert len(D)==len({r['rollout_key'] for r in D})==72
assert len(H)==len({r['rollout_key'] for r in H})==144

def costs(rr):
 failures=[r for r in rr if r.get('fatal')=='sequential_replay_failed']
 timed=[r for r in rr if 'seconds' in r]
 component=sum(sum(v['seconds'] for v in r.values() if isinstance(v,dict) and isinstance(v.get('seconds'),(int,float))) for r in failures)
 return dict(attempted_transitions=len(rr),failed_transitions=len(failures),consumer_sessions=sum('consumer' in r for r in rr),tool_calls=sum(r.get('consumer',{}).get('tool_calls',0) for r in rr),rows_with_total_seconds=len(timed),sum_available_total_seconds=sum(r['seconds'] for r in timed),failed_transition_recorded_component_seconds=component,warning='Failed transitions lack total elapsed seconds; component sums are recorded overhead only, not full compute/wall-clock cost. 1e9 in selector ranking is a penalty sentinel, never realized cost.')
bydev=defaultdict(list); byheld=defaultdict(list)
for r in D: bydev[r['anchor_id'],r['state_id']].append(r)
for r in H: byheld[r['anchor_id'],r['state_id']].append(r)
vals={k:mean(bool(r.get('strict_joint_success')) for r in rr) for k,rr in byheld.items()}
repo=[]; budget=[]
for repeats in [(0,), (1,), (0,1)]:
 selected=[]; used=[]; identity=[]
 for l in L:
  scores=[]
  for s in l['state_scores']:
   rr=[r for r in bydev[l['anchor_id'],s['state_id']] if r['repeat_index'] in repeats]
   assert len(rr)==len(repeats)
   used.extend(rr)
   scores.append((-mean(bool(r.get('strict_joint_success')) for r in rr),mean(r.get('consumer',{}).get('tool_calls',1e9) for r in rr),s['source_lines'],s['candidate_hash'],s['state_id']))
  choice=min(scores)[-1]
  if repeats==(0,1): assert choice==l['selected_state_id']
  selected.append(vals[l['anchor_id'],choice]); identity.append(choice)
 budget.append(dict(development_repeats=list(repeats),heldout_success=mean(selected),historical_choices=identity.count('historical'),**costs(used)))
seq=dict(status='Budget ablations are retrospective; full two-repeat selector was frozen before heldout outcomes.',development=costs(D),heldout=costs(H),budget_ablations=budget,zero_development_baselines={'historical':mean(vals[l['anchor_id'],'historical'] for l in L),'shortest_patch':mean(vals[l['anchor_id'],l['shortest_state_id']] for l in L),'uniform':mean(mean(vals[l['anchor_id'],s] for s in ['historical','s1']) for l in L)})
for l in L:
 repo.append(dict(repo=l['repo'],historical_heldout=vals[l['anchor_id'],'historical'],candidate_heldout=vals[l['anchor_id'],'s1'],**costs(sum((bydev[l['anchor_id'],s] for s in ['historical','s1']),[]))))
P=read('prospective_rsd_v3/continuation_selection_protocol/protocol.json')
producers=[]; dev=[]
for p,h in P['inputs'].items():
 rr=rows(p); assert sources[p]==h
 (producers if 'producer' in p else dev).extend(rr)
states=rows('prospective_rsd_v3/continuation_selection_protocol/frozen_states.jsonl')
a=read('prospective_rsd_v3/continuation_selection_analysis/analysis_yury_official.json')
def natural_cost(rr):
 return dict(rows=len(rr),prompt_tokens=sum(r.get('prompt_tokens',0) for r in rr),completion_tokens=sum(r.get('completion_tokens',0) for r in rr),generation_seconds=sum(r.get('generation_s',0) for r in rr))
cell=defaultdict(list)
for r in dev: cell[r['family'],r['source_sha256'],r['consumer'],r['future_id']].append(float(r['future_success']))
assert len(cell)==768
for s in states:
 vv=[mean(v) for k,v in cell.items() if k[:2]==(s['family'],s['state_sha256'])]
 assert len(vv)==12 and abs(mean(vv)-s['development_value'])<1e-12
natural=dict(production=natural_cost(producers),successful_production=sum(bool(r['current_success']) for r in producers),development=natural_cost(dev),development_cells=len(cell),unique_accepted_states=len(states),note='Raw development cost includes repeated producer instances of identical source hashes. Equal-cell aggregation changes weighting, not incurred cost. This is separate from the 18-repository panel.')
result=dict(sequential=seq,natural=natural,source_sha256=sources)
(OUT/'selector_cost_budget.json').write_text(json.dumps(result,indent=2)+'\n')
with (OUT/'selector_cost_by_repository.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(repo[0]));w.writeheader();w.writerows(repo)
print(json.dumps({'sequential':seq,'natural':natural},indent=2))
