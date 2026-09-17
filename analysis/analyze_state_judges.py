#!/usr/bin/env python3
"""Order-balanced semantic audit of pairwise LLM state judges."""
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument("inputs",nargs="+");p.add_argument("--output",required=True);a=p.parse_args();R=[]
for f in a.inputs:R += [json.loads(x) for x in open(f) if x.strip()]
for r in R:r["semantic_choice"]=("clean" if r["choice"]==r["gold"] else "debt") if r["choice"] else None
out={"n":len(R),"models":{}}
for m in sorted({r["model"] for r in R}):
 x=[r for r in R if r["model"]==m];paired=defaultdict(dict)
 for r in x:paired[(r["domain"],r["family"],r["sample"])][r["order"]]=r["semantic_choice"]
 both=[v for v in paired.values() if len(v)==2]
 out["models"][m]={"accuracy":float(np.mean([r["correct"] for r in x])),"choose_B_rate":float(np.mean([r["choice"]=="B" for r in x])),"invalid_rate":float(np.mean([r["choice"] is None for r in x])),"accuracy_by_order":{o:float(np.mean([r["correct"] for r in x if r["order"]==o])) for o in ("clean_first","debt_first")},"accuracy_by_domain":{d:float(np.mean([r["correct"] for r in x if r["domain"]==d])) for d in ("coding","enterprise")},"reversal_semantic_consistency":float(np.mean([v["clean_first"]==v["debt_first"] for v in both])) if both else None}
Path(a.output).write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out,indent=2))
