#!/usr/bin/env python3
"""Executable oracle preflight for every frozen held-out task."""

from continuation_selection_v1_tasks import HELDOUT_FUTURES
from empirical_continuation_suite import CASES, execute


ORACLES = {
"pricing": '''class PriceEngine:
    def __init__(self): self.rules={"basic":0.0,"pro":0.10}
    def price(self,plan,amount): return round(amount*(1-self.rules[plan]),2)
    def remove_plan(self,plan): return self.rules.pop(plan)
    def discounts(self): return dict(self.rules)
''',
"flags": '''class FeatureFlags:
    def __init__(self): self.flags={"search":False,"export":False}
    def set(self,name,enabled): self.flags[name]=bool(enabled)
    def get(self,name): return self.flags.get(name,False)
    def delete(self,name): return self.flags.pop(name,None)
    def enabled(self): return sorted(k for k,v in self.flags.items() if v)
''',
"permissions": '''class Permissions:
    def __init__(self): self.roles={"viewer":{"read"},"editor":{"read","write"}}
    def allowed(self,role,action): return action in self.roles.get(role,set())
    def grant(self,role,action): self.roles.setdefault(role,set()).add(action)
    def roles_for(self,action): return sorted(r for r,a in self.roles.items() if action in a)
''',
"events": '''class EventStore:
    def __init__(self): self.events=[]
    def record(self,user,value): self.events.append((user,value))
    def latest(self,user):
        vals=[v for u,v in self.events if u==user]; return vals[-1] if vals else None
    def first(self,user):
        vals=[v for u,v in self.events if u==user]; return vals[0] if vals else None
    def replace_latest(self,user,value):
        for i in range(len(self.events)-1,-1,-1):
            if self.events[i][0]==user:
                old=self.events[i][1]; self.events[i]=(user,value); return old
        return None
''',
"router": '''class Router:
    def __init__(self): self.routes={"/":"home","/health":"ok"}
    def resolve(self,path): return self.routes.get(path)
    def rename(self,old_path,new_path):
        if old_path not in self.routes: return None
        target=self.routes.pop(old_path); self.routes[new_path]=target; return target
    def paths_for(self,target): return sorted(p for p,t in self.routes.items() if t==target)
''',
"cache": '''class Cache:
    def __init__(self): self.data={}
    def put(self,key,value): self.data[key]=value
    def get(self,key): return self.data.get(key)
    def contains(self,key): return key in self.data
    def update_many(self,mapping): self.data.update(mapping)
''',
}


def main() -> None:
    failures=[]
    for family, futures in HELDOUT_FUTURES.items():
        for future_id, _requirement, test in futures:
            result=execute(ORACLES[family], CASES[family]["current"]+"\n"+test)
            print(f"{family}/{future_id}: {'PASS' if result['success'] else 'FAIL'}")
            if not result["success"]: failures.append((family,future_id,result["stderr"]))
    if failures: raise SystemExit(repr(failures))


if __name__ == "__main__": main()
