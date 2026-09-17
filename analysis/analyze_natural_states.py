#!/usr/bin/env python3
"""Analyze residual-state variation among naturally generated T0 successes."""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr

def main():
 p=argparse.ArgumentParser();p.add_argument("--producers",nargs="+",required=True);p.add_argument("--successors",nargs="+",required=True);p.add_argument("--output",required=True);a=p.parse_args();prod=[];succ=[]
 for f in a.producers:prod += [json.loads(x) for x in open(f) if x.strip()]
 for f in a.successors:succ += [json.loads(x) for x in open(f) if x.strip()]
 dedup={(r["consumer"],r["producer"],r["family"],r["producer_sample"],r["source_sha256"],r["future_id"]):r for r in succ};succ=list(dedup.values())
 good=[r for r in prod if r["current_success"]]; bystate=defaultdict(list)
 for r in succ:bystate[(r["family"],r["source_sha256"])].append(r)
 states=[]
 unique={}
 for s in good: unique.setdefault((s["family"],s["source_sha256"]),s)
 for k,s in unique.items():
  rs=bystate.get(k,[])
  if rs:states.append({"producers":sorted({r["producer"] for r in good if (r["family"],r["source_sha256"])==k}),"family":s["family"],"hash":s["source_sha256"],"value":float(np.mean([r["future_success"] for r in rs])),"n_rollouts":len(rs),"features":s.get("features",{})})
 fam=defaultdict(list)
 for s in states:fam[s["family"]].append(s)
 fr={}
 for f,x in fam.items():
  vals=np.array([z["value"] for z in x]);best=float(vals.max());fr[f]={"n_states":len(x),"mean":float(vals.mean()),"sd":float(vals.std()),"min":float(vals.min()),"max":best,"natural_debt_mean":float(np.mean(best-vals)),"fraction_nonzero_debt":float(np.mean(vals<best))}
 matrix=defaultdict(list)
 for r in succ:matrix[(r["producer"],r["consumer"])].append(r["future_success"])
 # Rank agreement of state values between successor models.
 cm=defaultdict(lambda:defaultdict(list))
 for r in succ:cm[r["consumer"]][(r["family"],r["source_sha256"])].append(r["future_success"])
 consumers=sorted(cm);agreements=[]
 for i in range(len(consumers)):
  for j in range(i+1,len(consumers)):
   keys=sorted(set(cm[consumers[i]])&set(cm[consumers[j]]));x=[np.mean(cm[consumers[i]][k]) for k in keys];y=[np.mean(cm[consumers[j]][k]) for k in keys]
   agreements.append({"a":consumers[i],"b":consumers[j],"n":len(keys),"spearman":float(spearmanr(x,y).statistic) if len(set(x))>1 and len(set(y))>1 else None})
 out={"producer_attempts":len(prod),"current_successes":len(good),"current_success_rate":len(good)/len(prod) if prod else None,"unique_successful_terminal_states":len(unique),"evaluated_unique_terminal_states":len(states),"families":fr,"producer_consumer_success":{"|".join(k):float(np.mean(v)) for k,v in matrix.items()},"consumer_rank_agreement":agreements,"states":states}
 Path(a.output).write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out,indent=2))
if __name__=="__main__":main()
