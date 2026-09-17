#!/usr/bin/env python3
"""Future-distribution sensitivity, rank reversals, and tail continuation risk."""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np

def category(fid):
    f=fid.lower()
    if any(x in f for x in ("history","audit","rollback","undo","checkpoint","reconstruct","invalid","oversell","bad_write","least")): return "governance_recovery"
    if any(x in f for x in ("rename","remove","delete","reset","clear","merge","revoke","restrict")): return "maintenance"
    return "extension"

def main():
    p=argparse.ArgumentParser(); p.add_argument("inputs",nargs="+"); p.add_argument("--output",required=True); a=p.parse_args()
    rows=[]
    for fn in a.inputs:
        rows += [json.loads(x) for x in open(fn) if x.strip()]
    g=defaultdict(dict)
    for r in rows: g[(r["model"],r["family"],r["variant"],r["future_id"],r["sample"])][r["state"]]=r
    pairs=[(k,d["clean"],d["debt"]) for k,d in g.items() if set(d)>={"clean","debt"}]
    scenarios={"uniform":lambda k:True,"extension":lambda k:category(k[3])=="extension",
               "maintenance":lambda k:category(k[3])=="maintenance","governance_recovery":lambda k:category(k[3])=="governance_recovery"}
    out={"n_pairs":len(pairs),"scenarios":{},"models":{}}
    for name,keep in scenarios.items():
        x=[z for z in pairs if keep(z[0])]
        if not x: continue
        dif=np.array([z[1]["future_success"]-z[2]["future_success"] for z in x],float)
        out["scenarios"][name]={"n":len(x),"clean_success":float(np.mean([z[1]["future_success"] for z in x])),
          "debt_success":float(np.mean([z[2]["future_success"] for z in x])),"state_debt":float(dif.mean()),
          "clean_only":int(np.sum(dif==1)),"debt_only_rank_reversals":int(np.sum(dif==-1)),
          "discordant_clean_share":float(np.mean(dif[dif!=0]>0)) if np.any(dif!=0) else None}
    # CVaR over task-level success rates, treating low continuation value as tail risk.
    for model in sorted({k[0] for k,_,_ in pairs}):
        x=[z for z in pairs if z[0][0]==model]; rec={}
        for state,idx in (("clean",1),("debt",2)):
            bytask=defaultdict(list)
            for z in x: bytask[(z[0][1],z[0][3])].append(z[idx]["future_success"])
            vals=np.sort([np.mean(v) for v in bytask.values()]); q=max(1,int(np.ceil(.25*len(vals))))
            rec[state]={"mean":float(vals.mean()),"cvar25_continuation":float(vals[:q].mean()),"worst_task":float(vals[0])}
        out["models"][model]=rec
    Path(a.output).write_text(json.dumps(out,indent=2)+"\n"); print(json.dumps(out,indent=2))
if __name__=="__main__": main()
