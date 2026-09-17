#!/usr/bin/env python3
"""Audit frozen T1 candidates by replaying the real first-parent history."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import tempfile
import time
import uuid
from collections import defaultdict
from pathlib import Path

from run_frontier_claude_calibration import DOCKERHUB, PRIME, proxy, q, ssh


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def execute(pair: dict, candidate: dict, integration: str) -> dict:
    future = pair["future"]
    image = future["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", pair["anchor_id"])
    container = f"rsd-frontier-replay-{stem}-{uuid.uuid4().hex[:6]}"
    row = {
        "anchor_id": pair["anchor_id"], "pair_id": pair["pair_id"],
        "candidate_id": f"cand_{candidate['candidate_hash'][:12]}",
        "candidate_hash": candidate["candidate_hash"], "sample": candidate.get("sample"),
        "container": container, "started_at": time.time(), "replay_success": False,
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
printf '%s\n' "$wd"
""")
    row["setup"] = setup
    if setup["returncode"]:
        row["fatal"] = "setup_failed"
        return row
    root = setup["output"].strip().splitlines()[-1]
    replay = "/tmp/rsd-sequential-replay"
    try:
        current_base = pair["current"]["base_commit"]
        future_base = future["base_commit"]
        row["worktree"] = proxy(
            "shell", container, root,
            command=f"git worktree add --detach {q(replay)} {q(current_base)}",
        )
        if row["worktree"]["returncode"]:
            row["fatal"] = "worktree_failed"
            return row
        with tempfile.TemporaryDirectory(prefix="rsd-replay-") as tmp:
            patch = Path(tmp) / "candidate.patch"
            patch.write_text(candidate["candidate_patch"])
            row["candidate_apply"] = proxy("apply", container, replay, patch=patch)
        if row["candidate_apply"]["returncode"]:
            row["fatal"] = "candidate_apply_failed"
            return row
        row["candidate_commit"] = proxy(
            "shell", container, replay,
            command=("git add -A && git -c user.name=RSD -c user.email=rsd@invalid "
                     "commit -m 'frozen alternative T1 state' >/dev/null && git rev-parse HEAD"),
        )
        if row["candidate_commit"]["returncode"]:
            row["fatal"] = "candidate_commit_failed"
            return row
        command = f"""
set -e
applied=0
empty=0
for commit in $(git rev-list --first-parent --reverse {q(current_base)}..{q(future_base)}); do
  if [ "$commit" = {q(integration)} ]; then
    continue
  fi
  parents=$(git rev-list --parents -n 1 "$commit" | awk '{{print NF-1}}')
  set +e
  if [ "$parents" -gt 1 ]; then
    git -c user.name=RSD -c user.email=rsd@invalid cherry-pick -m 1 "$commit" >/tmp/replay-step.log 2>&1
  else
    git -c user.name=RSD -c user.email=rsd@invalid cherry-pick "$commit" >/tmp/replay-step.log 2>&1
  fi
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    applied=$((applied+1))
  elif git diff --quiet && git diff --cached --quiet; then
    git cherry-pick --skip >/dev/null 2>&1 || true
    empty=$((empty+1))
  else
    unmerged=$(git diff --name-only --diff-filter=U)
    metadata_only=1
    for path in $unmerged; do
      lower=$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')
      case "$lower" in
        changelog*|changes*|history*|release*|citation*|docs/*|doc/*|*.md|*.rst|*.txt) ;;
        *) metadata_only=0 ;;
      esac
    done
    if [ -n "$unmerged" ] && [ "$metadata_only" -eq 1 ]; then
      echo "RSD_METADATA_CONFLICT=$commit:$unmerged"
      for path in $unmerged; do
        if git cat-file -e "$commit:$path" 2>/dev/null; then
          git show "$commit:$path" > "$path"
          git add "$path"
        else
          rm -f "$path"
          git add -u -- "$path"
        fi
      done
      git -c user.name=RSD -c user.email=rsd@invalid cherry-pick --continue \
        >/tmp/replay-continue.log 2>&1
      applied=$((applied+1))
    else
      echo "RSD_CODE_CONFLICT=$commit:$unmerged"
      cat /tmp/replay-step.log
      exit 42
    fi
  fi
done
echo "RSD_REPLAY_APPLIED=$applied"
echo "RSD_REPLAY_EMPTY=$empty"
git status --short
git rev-parse HEAD
"""
        row["replay"] = proxy("shell", container, replay, command=command, timeout=1200)
        row["replay_success"] = row["replay"]["returncode"] == 0
        match = re.search(r"RSD_CODE_CONFLICT=([0-9a-f]+):([^\n]*)", row["replay"]["output"])
        if match:
            row["conflict_commit"] = match.group(1)
            row["conflict_files"] = match.group(2).split()
        metadata = re.findall(r"RSD_METADATA_CONFLICT=([0-9a-f]+):([^\n]*)",
                              row["replay"]["output"])
        row["metadata_conflicts"] = [
            {"commit": commit, "files": files.split()} for commit, files in metadata
        ]
        row["final_status"] = proxy("status", container, replay)
        return row
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
        return row
    finally:
        row["finished_at"] = time.time()
        row["seconds"] = row["finished_at"] - row["started_at"]
        row["cleanup"] = ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", required=True, type=Path)
    parser.add_argument("--futures", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    anchors = json.loads(args.anchors.read_text())
    protocol = json.loads(args.protocol.read_text())
    pairs = {row["pair_id"]: row for row in read_jsonl(args.futures)}
    generated: dict[str, list[dict]] = defaultdict(list)
    for row in read_jsonl(args.candidates):
        if row.get("current_success") and row.get("frozen_gate_pass"):
            generated[row["pair_id"]].append(row)
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {(row["anchor_id"], row["candidate_hash"]) for row in previous}
    jobs = []
    for anchor in anchors:
        pair = pairs[anchor["audit_future_pair_id"]]
        integration = protocol["integration_commits"][anchor["anchor_id"]]
        for candidate in generated[anchor["pair_id"]]:
            if (anchor["anchor_id"], candidate["candidate_hash"]) not in done:
                jobs.append((pair, candidate, integration))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = [pool.submit(execute, *job) for job in jobs]
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                print(json.dumps({"anchor": row["anchor_id"],
                                  "candidate": row["candidate_id"],
                                  "replay_success": row["replay_success"],
                                  "conflict": row.get("conflict_commit"),
                                  "fatal": row.get("fatal")}), flush=True)


if __name__ == "__main__":
    main()
