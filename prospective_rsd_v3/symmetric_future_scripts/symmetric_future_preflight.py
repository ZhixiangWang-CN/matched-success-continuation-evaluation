#!/usr/bin/env python3
"""Deterministic feasibility gate for common-snapshot symmetric future tasks."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from run_frontier_claude_calibration import (
    DOCKERHUB, PRIME, patch_paths, proxy, q, run_pytest, ssh,
)
from run_frontier_conflict_recovery import read_jsonl


GIT_ID = "-c user.name=RSD -c user.email=rsd@invalid"


def compact(result: dict | None) -> dict | None:
    if result is None:
        return None
    out = dict(result)
    out["output"] = str(out.get("output", ""))[-5000:]
    if isinstance(out.get("node_attempt"), dict):
        out["node_attempt"] = compact(out["node_attempt"])
    return out


def apply_text(container: str, workdir: str, text: str, name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="rsd-symmetric-patch-") as tmp:
        path = Path(tmp) / name
        path.write_text(text)
        return compact(proxy("apply", container, workdir, patch=path, three_way=True))


def execute(job: dict, regression_cap: int) -> dict:
    pair, state = job["pair"], job["state"]
    current, future = pair["current"], pair["future"]
    image = current["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", pair["pair_id"] + "-" + state["state_id"])
    container = f"rsd-frontier-sympre-{stem[:90]}-{uuid.uuid4().hex[:6]}"
    row = {
        "preflight_key": job["key"], "pair_id": pair["pair_id"],
        "anchor_id": pair["anchor_id"], "future_pair_id": pair["pair_id"],
        "state_id": state["state_id"], "state_type": state["state_type"],
        "candidate_hash": state.get("candidate_hash"), "started_at": time.time(),
    }
    setup = ssh(f"""
set -e
docker create --name {q(container)} {q(image)} sleep infinity >/dev/null
docker start {q(container)} >/dev/null
wd=$(docker inspect -f '{{{{.Config.WorkingDir}}}}' {q(container)})
if [ ! -d "$wd/.git" ]; then
  gitdir=$(docker exec {q(container)} bash -lc 'find / -maxdepth 4 -type d -name .git 2>/dev/null | head -1')
  wd=${{gitdir%/.git}}
fi
docker network disconnect bridge {q(container)}
gitdir=$(docker exec {q(container)} bash -lc 'find / -maxdepth 4 -type d -name .git 2>/dev/null | head -1')
root=${{gitdir%/.git}}
docker exec -w "$root" {q(container)} bash -lc 'rm -rf /tmp/rsd-symmetric && git worktree add --detach /tmp/rsd-symmetric {q(current["base_commit"])}' >/dev/null
printf '%s\n' /tmp/rsd-symmetric
""")
    row["setup"] = compact(setup)
    if setup["returncode"]:
        row["fatal"] = "setup_failed"
        row["cleanup"] = compact(ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n"))
        return row
    workdir = "/tmp/rsd-symmetric"
    try:
        row["state_apply"] = apply_text(container, workdir, state["patch"], "state.patch")
        if row["state_apply"]["returncode"]:
            row["fatal"] = "state_apply_failed"
            return row
        row["state_commit"] = compact(proxy(
            "shell", container, workdir,
            command=f"git add -A && git {GIT_ID} commit -m 'frozen matched-success state' >/dev/null",
        ))

        row["current_test_apply"] = apply_text(
            container, workdir, current.get("test_patch", ""), "current-tests.patch")
        if row["current_test_apply"]["returncode"] == 0:
            row["current_test"] = compact(run_pytest(
                (container, workdir), current.get("FAIL_TO_PASS", []),
                current.get("test_patch", ""), timeout=1800))

        row["future_gold_apply"] = apply_text(
            container, workdir, future.get("patch", ""), "future-gold.patch")
        row["future_test_apply"] = apply_text(
            container, workdir, future.get("test_patch", ""), "future-tests.patch")
        if row["future_test_apply"]["returncode"] == 0 and row["future_gold_apply"]["returncode"] == 0:
            row["future_fail_to_pass"] = compact(run_pytest(
                (container, workdir), future.get("FAIL_TO_PASS", []),
                future.get("test_patch", ""), timeout=1800))
            row["future_pass_to_pass"] = compact(run_pytest(
                (container, workdir), list(future.get("PASS_TO_PASS", []))[:regression_cap],
                future.get("test_patch", ""), timeout=1800))
            row["current_after_future"] = compact(run_pytest(
                (container, workdir), current.get("FAIL_TO_PASS", []),
                current.get("test_patch", ""), timeout=1800))

        required = (
            row.get("state_apply", {}).get("returncode") == 0,
            row.get("current_test_apply", {}).get("returncode") == 0,
            row.get("current_test", {}).get("returncode") == 0,
            row.get("future_gold_apply", {}).get("returncode") == 0,
            row.get("future_test_apply", {}).get("returncode") == 0,
            row.get("future_fail_to_pass", {}).get("returncode") == 0,
            row.get("future_pass_to_pass", {}).get("returncode") == 0,
            row.get("current_after_future", {}).get("returncode") == 0,
        )
        row["eligible_state"] = all(required)
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
        row["eligible_state"] = False
    finally:
        row["cleanup"] = compact(ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n"))
        row["finished_at"] = time.time()
        row["seconds"] = row["finished_at"] - row["started_at"]
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--candidates", type=Path)
    p.add_argument("--arms", type=Path)
    p.add_argument("--historical-only", action="store_true",
                   help="Run the deterministic gate only on the historical state of every pair.")
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--docker-host", choices=["remote-host", "remote-host"])
    args = p.parse_args()

    if args.docker_host:
        os.environ.pop("RSD_DOCKER_LOCAL", None)
        os.environ["RSD_DOCKER_HOST"] = args.docker_host

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "FROZEN_BEFORE_SYMMETRIC_PREFLIGHT_RESULTS":
        raise SystemExit("preflight protocol is not frozen")
    pairs = {x["pair_id"]: x for x in read_jsonl(args.pairs)}
    if args.historical_only:
        candidates = {}
        by_pair = {pair_id: [] for pair_id in pairs}
    else:
        if not args.candidates or not args.arms:
            raise SystemExit("--candidates and --arms are required unless --historical-only is set")
        candidates = {x["candidate_hash"]: x for x in read_jsonl(args.candidates)}
        arms = json.loads(args.arms.read_text())["arms"]
        by_pair: dict[str, list[dict]] = {}
        for arm in arms:
            by_pair.setdefault(arm["future_pair_id"], []).append(arm)
    jobs = []
    for pair_id, state_arms in sorted(by_pair.items()):
        pair = pairs[pair_id]
        states = [{
            "state_id": "historical", "state_type": "historical",
            "candidate_hash": "historical", "patch": pair["current"]["patch"],
        }]
        for arm in sorted(state_arms, key=lambda x: x["state_index"]):
            candidate = candidates[arm["candidate_hash"]]
            states.append({
                "state_id": f"s{arm['state_index']}", "state_type": "candidate",
                "candidate_hash": arm["candidate_hash"], "patch": candidate["candidate_patch"],
            })
        for state in states:
            key = f"{pair_id}|{state['state_id']}"
            shard = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % args.num_shards
            if shard == args.shard_index:
                jobs.append({"key": key, "pair": pair, "state": state})

    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {x.get("preflight_key") for x in previous}
    jobs = [x for x in jobs if x["key"] not in done]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = __import__("threading").Lock()
    with args.output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(execute, job, protocol["design"]["future_regression_cap"]): job
                       for job in jobs}
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                with lock:
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                print(json.dumps({
                    "key": row["preflight_key"], "eligible": row.get("eligible_state"),
                    "fatal": row.get("fatal"), "seconds": round(row.get("seconds", 0)),
                }), flush=True)


if __name__ == "__main__":
    if "RSD_DOCKER_HOST" not in os.environ:
        os.environ.setdefault("RSD_DOCKER_LOCAL", "1")
    main()
