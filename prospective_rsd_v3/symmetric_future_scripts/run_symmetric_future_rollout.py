#!/usr/bin/env python3
"""Run frozen future tasks from matched states at one common repository snapshot."""
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
    DOCKERHUB, PRIME, parse_stream, patch_paths, proxy, q, run_pytest, ssh,
)
from run_frontier_conflict_recovery import future_prompt, read_jsonl, run_agent


GIT_ID = "-c user.name=RSD -c user.email=rsd@invalid"


def clipped(result: dict | None) -> dict | None:
    if result is None:
        return None
    out = dict(result)
    out["output"] = str(out.get("output", ""))[-30000:]
    return out


def apply_text(container: str, workdir: str, text: str, name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="rsd-symmetric-rollout-") as tmp:
        path = Path(tmp) / name
        path.write_text(text)
        return clipped(proxy("apply", container, workdir, patch=path))


def execute(job: dict, args: argparse.Namespace) -> dict:
    pair, state = job["pair"], job["state"]
    current, future = pair["current"], pair["future"]
    image = current["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", pair["pair_id"] + "-" + state["state_id"])
    container = f"rsd-frontier-symrun-{stem[:88]}-{uuid.uuid4().hex[:6]}"
    workdir = "/tmp/rsd-symmetric"
    row = {
        "rollout_key": job["key"], "protocol_id": job["protocol_id"],
        "pair_id": pair["pair_id"], "anchor_id": pair["anchor_id"],
        "repo": pair["repo"], "state_id": state["state_id"],
        "state_type": state["state_type"], "candidate_hash": state.get("candidate_hash"),
        "agent": args.agent, "model": args.model, "effort": args.effort,
        "repeat_index": job["repeat_index"],
        "started_at": time.time(), "common_base": current["base_commit"],
        "future_history_replay": False,
    }
    setup = ssh(f"""
set -e
docker create --name {q(container)} {q(image)} sleep infinity >/dev/null
docker start {q(container)} >/dev/null
docker network disconnect bridge {q(container)}
gitdir=$(docker exec {q(container)} bash -lc 'find / -maxdepth 4 -type d -name .git 2>/dev/null | head -1')
root=${{gitdir%/.git}}
docker exec -w "$root" {q(container)} bash -lc 'rm -rf {workdir} && git worktree add --detach {workdir} {q(current["base_commit"])}' >/dev/null
""")
    row["setup"] = clipped(setup)
    if setup["returncode"]:
        row["fatal"] = "setup_failed"
        row["cleanup"] = clipped(ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n"))
        return row
    try:
        row["state_apply"] = apply_text(container, workdir, state["patch"], "state.patch")
        if row["state_apply"]["returncode"]:
            row["fatal"] = "state_apply_failed"
            return row
        row["state_commit"] = clipped(proxy(
            "shell", container, workdir,
            command=f"git add -A && git {GIT_ID} commit -m 'frozen matched-success state' >/dev/null"))
        row["initial_status"] = clipped(proxy("status", container, workdir))

        log = args.logs / f"{stem}_{args.agent}_R{job['repeat_index']}.stream.jsonl"
        prompt = future_prompt(str(Path(__file__).resolve().parent / "frontier_container_proxy.py"),
                               container, workdir, pair["repo"], future["problem_statement"])
        row["consumer_returncode"] = run_agent(
            args.agent, args.model, args.effort, prompt, log, args.timeout,
            None, None, args.proxy_port, container, "future")
        row["consumer"] = parse_stream(log)
        row["agent_status"] = clipped(proxy("status", container, workdir))
        row["agent_diff"] = clipped(proxy(
            "shell", container, workdir,
            command="git diff --stat && git diff --numstat && git diff"))
        row["changed_by_agent"] = bool(row["agent_diff"]["output"].strip())

        # Remove any agent edits to benchmark-owned tests before installing hidden verifiers.
        test_paths = sorted(set(patch_paths(future.get("test_patch", "")) +
                                patch_paths(current.get("test_patch", ""))))
        if test_paths:
            restore = "; ".join(
                f"if git cat-file -e HEAD:{q(path)} 2>/dev/null; then git show HEAD:{q(path)} > {q(path)}; else rm -f {q(path)}; fi"
                for path in test_paths)
            row["oracle_test_restore"] = clipped(proxy(
                "shell", container, workdir, command=restore))
        row["future_test_apply"] = apply_text(
            container, workdir, future.get("test_patch", ""), "future-tests.patch")
        row["current_test_apply"] = apply_text(
            container, workdir, current.get("test_patch", ""), "current-tests.patch")
        if row["future_test_apply"]["returncode"] == 0:
            row["future_fail_to_pass"] = clipped(run_pytest(
                (container, workdir), future.get("FAIL_TO_PASS", []),
                future.get("test_patch", ""), timeout=1800))
            row["future_pass_to_pass"] = clipped(run_pytest(
                (container, workdir), list(future.get("PASS_TO_PASS", []))[:20],
                future.get("test_patch", ""), timeout=1800))
        if row["current_test_apply"]["returncode"] == 0:
            row["current_fail_to_pass"] = clipped(run_pytest(
                (container, workdir), current.get("FAIL_TO_PASS", []),
                current.get("test_patch", ""), timeout=1800))
        row["future_only_success"] = bool(
            row.get("future_fail_to_pass", {}).get("returncode") == 0 and
            row.get("future_pass_to_pass", {}).get("returncode") == 0)
        row["prior_preserved"] = bool(
            row.get("current_test_apply", {}).get("returncode") == 0 and
            row.get("current_fail_to_pass", {}).get("returncode") == 0)
        row["joint_success"] = row["future_only_success"] and row["prior_preserved"]
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
    finally:
        row["cleanup"] = clipped(ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n"))
        row["finished_at"] = time.time()
        row["seconds"] = row["finished_at"] - row["started_at"]
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--candidates", required=True, type=Path)
    p.add_argument("--arms", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--logs", required=True, type=Path)
    p.add_argument("--agent", choices=["codex", "claude"], required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", default="medium")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--proxy-port", type=int, default=18804)
    p.add_argument("--docker-host", choices=["remote-host", "remote-host"])
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--repeat-indices", type=int, nargs="+", default=[0])
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.docker_host:
        os.environ.pop("RSD_DOCKER_LOCAL", None)
        os.environ["RSD_DOCKER_HOST"] = args.docker_host

    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") not in {
        "FROZEN_BEFORE_ANY_SYMMETRIC_AGENT_OUTCOMES",
        "FROZEN_BEFORE_ANY_SYMMETRIC_REPEAT_OUTCOMES",
        "FROZEN_BEFORE_ANY_EXTENSION_FUTURE_OUTCOMES",
    }:
        raise SystemExit("symmetric rollout protocol is not frozen")
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("status") not in {
        "FROZEN_BEFORE_ANY_SYMMETRIC_AGENT_OUTCOMES",
        "FROZEN_BEFORE_ANY_EXTENSION_FUTURE_OUTCOMES",
    }:
        raise SystemExit("eligible manifest is not frozen")
    pair_ids = set(manifest["eligible_future_pair_ids"])
    if len(pair_ids) < protocol["eligibility"]["minimum_eligible_future_pairs"]:
        raise SystemExit("fewer than the predeclared minimum eligible future pairs")
    pairs = {x["pair_id"]: x for x in read_jsonl(args.pairs)}
    candidates = {x["candidate_hash"]: x for x in read_jsonl(args.candidates)}
    arms = json.loads(args.arms.read_text())["arms"]
    by_pair: dict[str, list[dict]] = {}
    for arm in arms:
        if arm["future_pair_id"] in pair_ids:
            by_pair.setdefault(arm["future_pair_id"], []).append(arm)

    jobs = []
    for pair_id in sorted(pair_ids):
        pair = pairs[pair_id]
        states = [{"state_id": "historical", "state_type": "historical",
                   "candidate_hash": "historical", "patch": pair["current"]["patch"]}]
        for arm in sorted(by_pair[pair_id], key=lambda x: x["state_index"]):
            candidate = candidates[arm["candidate_hash"]]
            states.append({"state_id": f"s{arm['state_index']}", "state_type": "candidate",
                           "candidate_hash": arm["candidate_hash"],
                           "patch": candidate["candidate_patch"]})
        expected_states = protocol.get("expected_states_per_pair", 3)
        if len(states) != expected_states:
            raise SystemExit(f"expected {expected_states} states for {pair_id}, got {len(states)}")
        for state in states:
            for repeat_index in sorted(set(args.repeat_indices)):
                key = f"{pair_id}|{state['state_id']}|{args.agent}|R{repeat_index}"
                shard = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % args.num_shards
                if shard == args.shard_index:
                    jobs.append({"key": key, "pair": pair, "state": state,
                                 "repeat_index": repeat_index,
                                 "protocol_id": protocol.get("protocol_id", manifest["protocol_id"])})
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {x.get("rollout_key") for x in previous}
    jobs = [x for x in jobs if x["key"] not in done]
    if args.dry_run:
        print(json.dumps({"pending": len(jobs), "pairs": len(pair_ids),
                          "shard": [args.shard_index, args.num_shards]}, indent=2))
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.logs.mkdir(parents=True, exist_ok=True)
    with args.output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(execute, job, args): job for job in jobs}
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                print(json.dumps({"key": row["rollout_key"],
                                  "joint": row.get("joint_success"),
                                  "future": row.get("future_only_success"),
                                  "prior": row.get("prior_preserved"),
                                  "fatal": row.get("fatal"),
                                  "seconds": round(row.get("seconds", 0))}), flush=True)


if __name__ == "__main__":
    main()
