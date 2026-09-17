#!/usr/bin/env python3
"""Matched-success terminal-state forks with executable hidden continuations.

Each clean/debt pair passes the same current-task verifier.  A fresh language
model receives one terminal state plus a future requirement and must return a
complete replacement module.  Its continuation is scored only by hidden tests.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fork:
    family: str
    variant: int
    state: str
    source: str
    current_test: str
    future_id: str
    requirement: str
    hidden_test: str


CASES = {
"pricing": {
"clean": '''class PriceEngine:
    def __init__(self):
        self.rules = {"basic": 0.0, "pro": 0.10}
    def price(self, plan, amount):
        return round(amount * (1 - self.rules[plan]), 2)
''',
"debt": '''class PriceEngine:
    def price(self, plan, amount):
        if plan == "basic": return round(amount, 2)
        if plan == "pro": return round(amount * 0.90, 2)
        raise KeyError(plan)
''',
"current": '''e=PriceEngine(); assert e.price("basic",100)==100; assert e.price("pro",100)==90''',
"futures": [
 ("add_plans", "Support enterprise (20% discount) and student (15% discount) plans while preserving existing behavior.", '''e=PriceEngine(); assert e.price("enterprise",200)==160; assert e.price("student",200)==170; assert e.price("pro",200)==180'''),
 ("runtime_rule", "Add set_discount(plan, fraction), allowing an arbitrary new plan to be configured at runtime.", '''e=PriceEngine(); e.set_discount("nonprofit",.25); assert e.price("nonprofit",80)==60; e.set_discount("pro",.3); assert e.price("pro",100)==70'''),
 ("composable", "Add price_with_promotions(plan, amount, promotions), applying plan discount then every fractional promotion in sequence.", '''e=PriceEngine(); assert e.price_with_promotions("pro",100,[.1,.2])==64.8; assert e.price_with_promotions("basic",50,[])==50'''),
 ("rename", "Add rename_plan(old, new); after renaming the old name must be invalid and the new one retain the discount.", '''e=PriceEngine(); e.rename_plan("pro","team"); assert e.price("team",100)==90\ntry: e.price("pro",100); assert False\nexcept KeyError: pass'''),
]},
"flags": {
"clean": '''class FeatureFlags:
    def __init__(self):
        self.flags = {"search": False, "export": False}
    def set(self, name, enabled): self.flags[name] = bool(enabled)
    def get(self, name): return self.flags.get(name, False)
''',
"debt": '''class FeatureFlags:
    def __init__(self): self.search=False; self.export=False
    def set(self, name, enabled):
        if name=="search": self.search=bool(enabled)
        elif name=="export": self.export=bool(enabled)
        else: raise ValueError(name)
    def get(self, name):
        if name=="search": return self.search
        if name=="export": return self.export
        return False
''',
"current": '''f=FeatureFlags(); assert not f.get("search"); f.set("search",True); assert f.get("search"); assert not f.get("missing")''',
"futures": [
 ("arbitrary", "Allow set/get for arbitrary feature names, with unknown features initially disabled.", '''f=FeatureFlags(); f.set("dark_launch",True); assert f.get("dark_launch"); assert not f.get("other")'''),
 ("snapshot", "Add snapshot() returning a detached dictionary of every configured feature and its boolean value.", '''f=FeatureFlags(); f.set("search",True); s=f.snapshot(); assert s=={"search":True,"export":False}; s["search"]=False; assert f.get("search")'''),
 ("bulk", "Add set_many(mapping) which atomically validates all values are bool before changing any flag.", '''f=FeatureFlags(); f.set_many({"search":True,"new":False}); assert f.get("search") and not f.get("new")\ntry: f.set_many({"export":True,"bad":1}); assert False\nexcept (TypeError,ValueError): pass\nassert not f.get("export")'''),
 ("rollback", "Add checkpoint() and rollback(checkpoint) so all feature changes after a checkpoint can be undone.", '''f=FeatureFlags(); c=f.checkpoint(); f.set("search",True); f.set("export",True); f.rollback(c); assert not f.get("search") and not f.get("export")'''),
]},
"permissions": {
"clean": '''class Permissions:
    def __init__(self): self.roles={"viewer":{"read"},"editor":{"read","write"}}
    def allowed(self, role, action): return action in self.roles.get(role,set())
''',
"debt": '''class Permissions:
    def allowed(self, role, action):
        if role=="viewer": return action=="read"
        if role=="editor": return action in ("read","write")
        return False
''',
"current": '''p=Permissions(); assert p.allowed("viewer","read"); assert not p.allowed("viewer","write"); assert p.allowed("editor","write")''',
"futures": [
 ("custom_role", "Add define_role(name, actions), supporting arbitrary roles and replacing an existing role definition.", '''p=Permissions(); p.define_role("auditor",{"read","audit"}); assert p.allowed("auditor","audit"); p.define_role("viewer",set()); assert not p.allowed("viewer","read")'''),
 ("inheritance", "Add define_role(name, actions, inherits=None); inherited permissions must be resolved transitively.", '''p=Permissions(); p.define_role("author",{"comment"},inherits="viewer"); p.define_role("lead",{"approve"},inherits="author"); assert all(p.allowed("lead",a) for a in ["read","comment","approve"])'''),
 ("revoke", "Add revoke(role, action), removing only that role's action without affecting other roles.", '''p=Permissions(); p.revoke("editor","write"); assert not p.allowed("editor","write"); assert p.allowed("editor","read") and p.allowed("viewer","read")'''),
 ("least_privilege", "Add effective(role) returning a detached set and restrict(role, allowed_actions) intersecting current permissions with the supplied set.", '''p=Permissions(); x=p.effective("editor"); x.clear(); assert p.allowed("editor","read"); p.restrict("editor",{"read"}); assert p.effective("editor")=={"read"}'''),
]},
"events": {
"clean": '''class EventStore:
    def __init__(self): self.events=[]
    def record(self, user, value): self.events.append((user,value))
    def latest(self, user):
        vals=[v for u,v in self.events if u==user]
        return vals[-1] if vals else None
''',
"debt": '''class EventStore:
    def __init__(self): self.values={}
    def record(self, user, value): self.values[user]=value
    def latest(self, user): return self.values.get(user)
''',
"current": '''s=EventStore(); assert s.latest("a") is None; s.record("a",1); s.record("b",4); assert s.latest("a")==1''',
"futures": [
 ("history", "Add history(user), returning all that user's recorded values in chronological order.", '''s=EventStore(); s.record("a",1); s.record("a",2); s.record("b",9); assert s.history("a")==[1,2] and s.history("b")==[9]'''),
 ("undo", "Add undo(user), removing and returning that user's latest event while revealing their preceding value; return None if absent.", '''s=EventStore(); s.record("a",1); s.record("a",2); assert s.undo("a")==2; assert s.latest("a")==1; assert s.undo("a")==1; assert s.latest("a") is None'''),
 ("audit", "Add audit(), returning all (user,value) events globally in exact insertion order.", '''s=EventStore(); s.record("a",1); s.record("b",2); s.record("a",3); assert s.audit()==[("a",1),("b",2),("a",3)]'''),
 ("count", "Add count(user=None): per-user count when supplied, otherwise total number of recorded events.", '''s=EventStore(); s.record("a",1); s.record("a",2); s.record("b",3); assert s.count()==3 and s.count("a")==2 and s.count("x")==0'''),
]},
"router": {
"clean": '''class Router:
    def __init__(self): self.routes={"/":"home","/health":"ok"}
    def resolve(self,path): return self.routes.get(path)
''',
"debt": '''class Router:
    def resolve(self,path):
        if path=="/": return "home"
        if path=="/health": return "ok"
        return None
''',
"current": '''r=Router(); assert r.resolve("/")=="home"; assert r.resolve("/health")=="ok"; assert r.resolve("/x") is None''',
"futures": [
 ("dynamic_route", "Add add(path, target), supporting arbitrary runtime routes and replacement.", '''r=Router(); r.add("/users","users"); assert r.resolve("/users")=="users"; r.add("/","landing"); assert r.resolve("/")=="landing"'''),
 ("remove_route", "Add remove(path), returning the removed target or None.", '''r=Router(); assert r.remove("/health")=="ok"; assert r.resolve("/health") is None; assert r.remove("/missing") is None'''),
 ("fallback", "Add set_fallback(target); unresolved paths then return the fallback while known paths remain unchanged.", '''r=Router(); r.set_fallback("404"); assert r.resolve("/x")=="404" and r.resolve("/")=="home"'''),
 ("snapshot_routes", "Add snapshot() returning a detached mapping of every exact route.", '''r=Router(); s=r.snapshot(); assert s=={"/":"home","/health":"ok"}; s.clear(); assert r.resolve("/")=="home"'''),
]},
"cache": {
"clean": '''class Cache:
    def __init__(self): self.data={}
    def put(self,key,value): self.data[key]=value
    def get(self,key): return self.data.get(key)
''',
"debt": '''class Cache:
    def __init__(self): self.last_key=None; self.last_value=None
    def put(self,key,value): self.last_key=key; self.last_value=value
    def get(self,key): return self.last_value if key==self.last_key else None
''',
"current": '''c=Cache(); assert c.get("a") is None; c.put("a",1); assert c.get("a")==1''',
"futures": [
 ("multiple_keys", "Store multiple keys simultaneously without evicting earlier keys.", '''c=Cache(); c.put("a",1); c.put("b",2); assert c.get("a")==1 and c.get("b")==2'''),
 ("delete_key", "Add delete(key), returning its value or None and leaving other keys untouched.", '''c=Cache(); c.put("a",1); c.put("b",2); assert c.delete("a")==1; assert c.get("a") is None and c.get("b")==2'''),
 ("cache_items", "Add items() returning a detached dictionary of all cached entries.", '''c=Cache(); c.put("a",1); c.put("b",2); x=c.items(); assert x=={"a":1,"b":2}; x.clear(); assert c.get("a")==1'''),
 ("clear_cache", "Add clear() removing all entries and returning the number removed.", '''c=Cache(); c.put("a",1); c.put("b",2); assert c.clear()==2; assert c.get("a") is None and c.get("b") is None'''),
]}}


def variants(source: str, variant: int) -> str:
    """Semantics-preserving surface perturbations prevent template memorization."""
    if variant == 0:
        return source
    return ("# Workspace variant %d\n" % variant) + source.replace("self.", f"self.")


def build_forks(n_variants: int) -> list[Fork]:
    out=[]
    for family, spec in CASES.items():
        for v in range(n_variants):
            for state in ("clean","debt"):
                for fid, req, test in spec["futures"]:
                    out.append(Fork(family,v,state,variants(spec[state],v),spec["current"],fid,req,test))
    return out


def extract_code(text: str) -> str:
    blocks=re.findall(r"```(?:python)?\s*(.*?)```",text,re.S|re.I)
    code=max(blocks,key=len) if blocks else text
    code=code.strip()
    if code.startswith("Here is") and "\n" in code: code=code.split("\n",1)[1]
    return code


def execute(source: str, test: str, timeout: float=4.0) -> dict:
    payload=source+"\n\n"+test+"\n"
    t=time.perf_counter()
    try:
        ast.parse(source)
        p=subprocess.run([os.environ.get("PYTHON","python3"),"-I","-c",payload],capture_output=True,text=True,timeout=timeout)
        return {"success":p.returncode==0,"returncode":p.returncode,"stderr":p.stderr[-1000:],"runtime_s":time.perf_counter()-t}
    except Exception as e:
        return {"success":False,"returncode":-1,"stderr":repr(e),"runtime_s":time.perf_counter()-t}


def prompt(f: Fork) -> str:
    return f'''You maintain a small Python module. Implement the new requirement while preserving all existing behavior.
Return ONLY the complete replacement Python module, inside one python code block. Do not return tests or explanation.

CURRENT MODULE:
```python
{f.source}
```

NEW REQUIREMENT:
{f.requirement}
'''


def structural_features(source: str) -> dict:
    tree=ast.parse(source)
    return {"loc":len(source.splitlines()),"chars":len(source),"ifs":sum(isinstance(x,ast.If) for x in ast.walk(tree)),
            "dicts":sum(isinstance(x,ast.Dict) for x in ast.walk(tree)),"lists":sum(isinstance(x,ast.List) for x in ast.walk(tree)),
            "methods":sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) for x in ast.walk(tree))}


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--model",required=True)
    ap.add_argument("--model-name",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--variants",type=int,default=2)
    ap.add_argument("--samples",type=int,default=2)
    ap.add_argument("--temperature",type=float,default=.2)
    ap.add_argument("--max-new-tokens",type=int,default=900)
    ap.add_argument("--limit",type=int)
    args=ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok=AutoTokenizer.from_pretrained(args.model,trust_remote_code=True)
    model=AutoModelForCausalLM.from_pretrained(args.model,torch_dtype="auto",device_map="auto",trust_remote_code=True)
    model.eval()
    forks=build_forks(args.variants)
    if args.limit: forks=forks[:args.limit]
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    current=[]
    for f in forks:
        r=execute(f.source,f.current_test)
        current.append(r["success"])
    if not all(current): raise RuntimeError(f"Current-state verifier failed: {sum(current)}/{len(current)}")

    with out.open("a",encoding="utf-8") as fh:
        for i,f in enumerate(forks):
            for sample in range(args.samples):
                seed=1701+sample+100*f.variant
                torch.manual_seed(seed)
                messages=[{"role":"system","content":"You are a precise software engineer."},{"role":"user","content":prompt(f)}]
                try:
                    rendered=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
                except Exception as e:
                    if "System role not supported" not in str(e): raise
                    rendered=tok.apply_chat_template([{"role":"user","content":"You are a precise software engineer.\n\n"+prompt(f)}],tokenize=False,add_generation_prompt=True)
                inputs=tok(rendered,return_tensors="pt").to(model.device)
                t=time.perf_counter()
                with torch.no_grad():
                    y=model.generate(**inputs,max_new_tokens=args.max_new_tokens,do_sample=args.temperature>0,
                                     temperature=max(args.temperature,1e-5),top_p=.95,pad_token_id=tok.eos_token_id,
                                     use_cache=False if "phi" in args.model_name.lower() else True)
                elapsed=time.perf_counter()-t
                new=y[0,inputs.input_ids.shape[1]:]
                raw=tok.decode(new,skip_special_tokens=True)
                code=extract_code(raw)
                result=execute(code,f.current_test+"\n"+f.hidden_test)
                rec={"model":args.model_name,"family":f.family,"variant":f.variant,"state":f.state,
                     "future_id":f.future_id,"sample":sample,"seed":seed,"current_success":True,
                     "future_success":result["success"],"returncode":result["returncode"],"stderr":result["stderr"],
                     "generation_s":elapsed,"execution_s":result["runtime_s"],"prompt_tokens":int(inputs.input_ids.numel()),
                     "completion_tokens":int(new.numel()),"input_features":structural_features(f.source),
                     "output_chars":len(code),"source_sha256":hashlib.sha256(f.source.encode()).hexdigest(),"raw":raw}
                fh.write(json.dumps(rec,ensure_ascii=False)+"\n"); fh.flush()
                print(json.dumps({k:rec[k] for k in ("model","family","variant","state","future_id","sample","future_success")}),flush=True)

if __name__=="__main__": main()
