#!/usr/bin/env python3
"""Nonlinear AST critic with leave-family-out and cross-consumer evaluation."""
import argparse,ast,json
from collections import defaultdict
from pathlib import Path
import numpy as np
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor

FEATURES=("chars","lines","nodes","ifs","ifexprs","dicts","sequences","compares","boolops","subscripts","state_ops","raises","assigns","methods","literals","unique_literals","returns")
def ast_features(src):
 t=ast.parse(src);n=list(ast.walk(t));l=[x.value for x in n if isinstance(x,ast.Constant) and isinstance(x.value,(str,int,float))]
 return [len(src),len(src.splitlines()),len(n),sum(isinstance(x,ast.If) for x in n),sum(isinstance(x,ast.IfExp) for x in n),sum(isinstance(x,ast.Dict) for x in n),sum(isinstance(x,(ast.List,ast.Set,ast.Tuple)) for x in n),sum(isinstance(x,ast.Compare) for x in n),sum(isinstance(x,ast.BoolOp) for x in n),sum(isinstance(x,ast.Subscript) for x in n),sum(isinstance(x,ast.Attribute) and x.attr in ("append","get","setdefault","update") for x in n),sum(isinstance(x,ast.Raise) for x in n),sum(isinstance(x,ast.Assign) for x in n),sum(isinstance(x,ast.FunctionDef) for x in n),len(l),len(set(map(str,l))),sum(isinstance(x,ast.Return) for x in n)]

p=argparse.ArgumentParser();p.add_argument("--producers",nargs="+",required=True);p.add_argument("--successors",nargs="+",required=True);p.add_argument("--output",required=True);a=p.parse_args();P=[];S=[]
for f in a.producers:P += [json.loads(x) for x in open(f) if x.strip()]
for f in a.successors:S += [json.loads(x) for x in open(f) if x.strip()]
S=list({(r["consumer"],r["family"],r["source_sha256"],r["future_id"]):r for r in S}.values())
values=defaultdict(list)
for r in S:values[(r["consumer"],r["family"],r["source_sha256"])].append(r["future_success"])
consumers=sorted({r["consumer"] for r in S});source={}
for r in P:
 if r["current_success"]:source.setdefault((r["family"],r["source_sha256"]),r["source"])
states=[]
for (fam,h),src in source.items():
 labs={c:float(np.mean(values[(c,fam,h)])) for c in consumers if values[(c,fam,h)]}
 if labs:
  try:states.append({"family":fam,"hash":h,"source":src,"x":ast_features(src),"chars":len(src),"labels":labs})
  except Exception:pass

def run(train_consumer):
 rows=[];all_true=[];all_pred=[]
 for fam in sorted({r["family"] for r in states}):
  train=[r for r in states if r["family"]!=fam and (train_consumer=="pooled" or train_consumer in r["labels"])]
  test=[r for r in states if r["family"]==fam and (train_consumer=="pooled" or train_consumer in r["labels"])]
  if not train or not test:continue
  y=[1-(np.mean(list(r["labels"].values())) if train_consumer=="pooled" else r["labels"][train_consumer]) for r in train]
  model=RandomForestRegressor(n_estimators=1000,min_samples_leaf=2,max_features=.8,random_state=1701,n_jobs=-1).fit([r["x"] for r in train],y)
  pred=model.predict([r["x"] for r in test]);chosen=test[int(np.argmin(pred))];short=min(test,key=lambda r:r["chars"])
  for r,q in zip(test,pred):
   true=1-(np.mean(list(r["labels"].values())) if train_consumer=="pooled" else r["labels"][train_consumer]);all_true.append(true);all_pred.append(q)
  evals={}
  for c in consumers:
   eligible=[r for r in test if c in r["labels"]]
   if not eligible or c not in chosen["labels"] or c not in short["labels"]:continue
   vals=[r["labels"][c] for r in eligible]
   evals[c]={"critic":chosen["labels"][c],"random":float(np.mean(vals)),"shortest":short["labels"][c],"oracle":float(max(vals))}
  rows.append({"family":fam,"n_candidates":len(test),"chosen_hash":chosen["hash"],"evaluations":evals})
 agg={}
 for c in consumers:
  z=[r["evaluations"][c] for r in rows if c in r["evaluations"]]
  if z:agg[c]={k:float(np.mean([q[k] for q in z])) for k in ("critic","random","shortest","oracle")}
 return {"families":rows,"aggregate_by_evaluation_consumer":agg,"state_prediction_mae":float(np.mean(np.abs(np.array(all_true)-all_pred))),"state_prediction_spearman":float(spearmanr(all_true,all_pred).statistic) if len(set(all_true))>1 else None}

out={"features":FEATURES,"n_unique_states":len(states),"consumers":consumers,"train_pooled":run("pooled"),"train_by_consumer":{c:run(c) for c in consumers}}
Path(a.output).write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out,indent=2))
