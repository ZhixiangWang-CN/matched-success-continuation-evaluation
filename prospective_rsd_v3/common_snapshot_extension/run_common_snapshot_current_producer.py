#!/usr/bin/env python3
"""Generate frozen current-task alternatives for the repository-disjoint extension."""
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

from run_frontier_claude_calibration import DOCKERHUB, PRIME, parse_stream, proxy, q, run_pytest, ssh
from run_frontier_conflict_recovery import future_prompt, read_jsonl, run_agent


def clipped(result: dict | None) -> dict | None:
    if result is None:
        return None
    out = dict(result)
    out["output"] = str(out.get("output", ""))[-30000:]
    return out


def apply_text(container: str, workdir: str, text: str, name: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="rsd-extension-current-") as tmp:
        path = Path(tmp) / name
        path.write_text(text)
        return clipped(proxy("apply", container, workdir, patch=path))


def patch_paths(patch: str) -> list[str]:
    return sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)))


def normalized_hash(patch: str) -> str:
    text = "\n".join(line for line in patch.splitlines()
                     if not line.startswith(("index ", "--- ", "+++ ")))
    return hashlib.sha256(text.encode()).hexdigest()


def execute(job: dict, args: argparse.Namespace) -> dict:
    pair = job["pair"]
    current = pair["current"]
    image = current["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", pair["pair_id"])
    container = f"rsd-frontier-extension-producer-{stem[:63]}-R{job['attempt']}-{uuid.uuid4().hex[:6]}"
    workdir = "/tmp/rsd-extension-current"
    row = {
        "rollout_key": job["key"], "protocol_id": job["protocol_id"],
        "pair_id": pair["pair_id"], "anchor_id": pair["anchor_id"], "repo": pair["repo"],
        "attempt_index": job["attempt"], "agent": "codex", "model": args.model,
        "effort": args.effort, "started_at": time.time(), "common_base": current["base_commit"],
        "future_information_exposed": False,
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
        log = args.logs / f"{stem}_R{job['attempt']}.stream.jsonl"
        prompt = future_prompt(str(Path(__file__).resolve().parent / "frontier_container_proxy.py"),
                               container, workdir, pair["repo"], current["problem_statement"])
        row["consumer_returncode"] = run_agent("codex", args.model, args.effort, prompt, log,
                                                args.timeout, None, None, 0, container, "current")
        row["consumer"] = parse_stream(log)
        diff_result = clipped(proxy("shell", container, workdir, command="git diff --binary"))
        patch = diff_result["output"] if diff_result and diff_result.get("returncode") == 0 else ""
        paths = patch_paths(patch)
        test_edits = [path for path in paths if "test" in path.lower()]
        row["candidate_patch"] = patch
        row["candidate_hash"] = normalized_hash(patch)
        row["changed_paths"] = paths
        row["nonempty"] = bool(patch.strip())
        row["no_test_edit"] = not test_edits
        row["test_edits"] = test_edits

        # Restore any attempted edits to benchmark-owned tests before installing hidden tests.
        if test_edits:
            restore = "; ".join(
                f"if git cat-file -e HEAD:{q(path)} 2>/dev/null; then git show HEAD:{q(path)} > {q(path)}; else rm -f {q(path)}; fi"
                for path in test_edits)
            row["test_restore"] = clipped(proxy("shell", container, workdir, command=restore))
        row["current_test_apply"] = apply_text(container, workdir, current.get("test_patch", ""),
                                                "current-tests.patch")
        if row["current_test_apply"]["returncode"] == 0:
            row["current_fail_to_pass"] = clipped(run_pytest(
                (container, workdir), current.get("FAIL_TO_PASS", []), current.get("test_patch", ""),
                timeout=1800))
            row["current_pass_to_pass"] = clipped(run_pytest(
                (container, workdir), list(current.get("PASS_TO_PASS", []))[:20],
                current.get("test_patch", ""), timeout=1800))
        row["current_success"] = bool(
            row["nonempty"] and row["no_test_edit"] and
            row.get("current_test_apply", {}).get("returncode") == 0 and
            row.get("current_fail_to_pass", {}).get("returncode") == 0 and
            row.get("current_pass_to_pass", {}).get("returncode") == 0
        )
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
        row["current_success"] = False
    finally:
        row["cleanup"] = clipped(ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n"))
        row["finished_at"] = time.time()
        row["seconds"] = row["finished_at"] - row["started_at"]
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--logs", required=True, type=Path)
    p.add_argument("--model", default="gpt-5.6-sol")
    p.add_argument("--effort", default="medium")
    p.add_argument("--attempt-indices", nargs="+", type=int, default=[0, 1])
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--docker-host", choices=["remote-host", "remote-host"], required=True)
    p.add_argument("--num-shards", type=int, default=1)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    os.environ.pop("RSD_DOCKER_LOCAL", None)
    os.environ["RSD_DOCKER_HOST"] = args.docker_host
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("status") != "FROZEN_BEFORE_ANY_EXTENSION_AGENT_OUTCOMES":
        raise SystemExit("extension protocol is not frozen")
    pairs = read_jsonl(args.pairs)
    jobs = []
    for pair in pairs:
        for attempt in sorted(set(args.attempt_indices)):
            key = f"{pair['pair_id']}|producer|R{attempt}"
            shard = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big") % args.num_shards
            if shard == args.shard_index:
                jobs.append({"key": key, "pair": pair, "attempt": attempt,
                             "protocol_id": protocol["protocol_id"]})
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {row.get("rollout_key") for row in previous}
    jobs = [job for job in jobs if job["key"] not in done]
    if args.dry_run:
        print(json.dumps({"pending": len(jobs), "shard": [args.shard_index, args.num_shards]}, indent=2))
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.logs.mkdir(parents=True, exist_ok=True)
    with args.output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(execute, job, args): job for job in jobs}
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                handle.write(json.dumps(row) + "\n"); handle.flush()
                print(json.dumps({"key": row["rollout_key"], "success": row.get("current_success"),
                                  "fatal": row.get("fatal"), "seconds": round(row.get("seconds", 0))}),
                      flush=True)


if __name__ == "__main__":
    main()
