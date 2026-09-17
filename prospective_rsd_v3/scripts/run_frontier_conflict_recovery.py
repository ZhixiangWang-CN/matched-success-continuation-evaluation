#!/usr/bin/env python3
"""Agent-mediated conflict recovery for the frozen heldout arms that stopped at a source conflict.

For every heldout arm whose strict sequential replay stopped at a source-code conflict, this
runner (1) replays the real first-parent history onto the frozen alternative state exactly as
the strict protocol does, (2) at each source conflict hands the in-progress cherry-pick to the
same frontier consumer with a recovery prompt that does not mention the future task, (3) resumes
replay after a verified resolution, and (4) then runs the unchanged future-task consumer session
and the unchanged strict evaluation.  Recovery probability, recovery cost, and post-recovery
continuation are recorded separately, as the paper's estimand requires.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from frontier_proxy_server import serve
from run_frontier_claude_calibration import (
    DOCKERHUB, PRIME, PROXY, parse_stream, patch_paths, proxy, q, run_pytest, ssh,
)

CODEX_BIN = (os.environ.get("CODEX_BIN") or shutil.which("codex")
             or "/Applications/ChatGPT.app/Contents/Resources/codex")
REPLAY_WORKDIR = "/tmp/rsd-sequential-replay"
GIT_ID = "-c user.name=RSD -c user.email=rsd@invalid"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def replay_script(current_base: str, future_base: str, integration: str,
                  resume_after: str | None) -> str:
    """Strict first-parent replay; on a source conflict leave the cherry-pick in progress."""
    skip = f'skipping={1 if resume_after else 0}'
    resume = q(resume_after or "")
    return f"""
set -e
applied=0
empty=0
metadata_conflicts=0
{skip}
for commit in $(git rev-list --first-parent --reverse {q(current_base)}..{q(future_base)}); do
  if [ "$skipping" -eq 1 ]; then
    if [ "$commit" = {resume} ]; then skipping=0; fi
    continue
  fi
  if [ "$commit" = {q(integration)} ]; then continue; fi
  parents=$(git rev-list --parents -n 1 "$commit" | awk '{{print NF-1}}')
  set +e
  if [ "$parents" -gt 1 ]; then
    git {GIT_ID} cherry-pick -m 1 "$commit" >/tmp/replay-step.log 2>&1
  else
    git {GIT_ID} cherry-pick "$commit" >/tmp/replay-step.log 2>&1
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
          git show "$commit:$path" > "$path"; git add "$path"
        else
          rm -f "$path"; git add -u -- "$path"
        fi
      done
      GIT_EDITOR=true git {GIT_ID} cherry-pick --continue >/tmp/replay-continue.log 2>&1
      metadata_conflicts=$((metadata_conflicts+1))
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
echo "RSD_METADATA_CONFLICTS=$metadata_conflicts"
git status --short
"""


def recovery_prompt(agent_proxy: str, container: str, workdir: str, repo: str,
                    commit: str, files: list[str], subject: str) -> str:
    listed = ", ".join(files)
    return f"""You are a software maintainer replaying upstream history onto a repository state in a frozen research evaluation.
Inside the isolated Docker repository, `git cherry-pick` of upstream commit {commit} ("{subject}") stopped with a merge conflict in: {listed}.
Resolve the conflict so that the intent of the upstream commit is preserved AND the behavior already present in the repository state is kept. Do not simply discard one side.

Rules:
- Do not use the internet.
- Do not use git reset, git checkout, git restore, git stash, git rebase, git cherry-pick --abort, or git cherry-pick --skip.
- You may inspect history with git log, git show, and git diff, and you may run tests.
- Keep edits minimal and do not modify unrelated files.
- After editing, stage the resolved files with `git add <file>` and finish with:
  GIT_EDITOR=true git -c user.name=RSD -c user.email=rsd@invalid cherry-pick --continue
- If the conflict cannot be resolved faithfully, stop and leave it unresolved.

You may operate ONLY through these commands:
- Inspect or test: python3 {agent_proxy} shell --container {container} --workdir {workdir} --command '<shell command>'
- Apply an edit: write a unified diff to /tmp/{container}.patch, then run python3 {agent_proxy} apply --container {container} --workdir {workdir} --patch /tmp/{container}.patch
- Check final state: python3 {agent_proxy} status --container {container} --workdir {workdir}

Do not inspect any local workspace files.

Repository: {repo}
"""


def future_prompt(agent_proxy: str, container: str, workdir: str, repo: str,
                  problem_statement: str) -> str:
    # Byte-identical to the frozen heldout consumer prompt in run_frontier_claude_calibration.py.
    return f"""You are the future software-engineering consumer in a frozen research evaluation.
Solve the issue below in the isolated Docker repository. Hidden evaluation tests are not available to you.
Do not use the internet, git history, git reset, or git checkout. Preserve prior behavior and keep edits minimal.

You may operate ONLY through these commands:
- Inspect or test: python3 {agent_proxy} shell --container {container} --workdir {workdir} --command '<shell command>'
- Apply an edit: write a unified diff to /tmp/{container}.patch, then run python3 {agent_proxy} apply --container {container} --workdir {workdir} --patch /tmp/{container}.patch
- Check final state: python3 {agent_proxy} status --container {container} --workdir {workdir}

Do not inspect any local workspace files. First inspect the relevant implementation, reproduce when practical,
then edit and test. End only when the repository implementation is ready.

Repository: {repo}
Issue:
{problem_statement}
"""


def run_agent(agent: str, model: str, effort: str, prompt: str, log: Path, timeout: int,
              claude_host: str | None, proxy_token: str | None, proxy_port: int,
              container: str, tag: str) -> int:
    with log.open("w") as handle:
        if agent == "claude" and claude_host:
            remote_prompt = f"/tmp/{container}.{tag}.prompt"
            subprocess.run(["ssh", claude_host, "bash", "-lc", repr(f"cat > {remote_prompt}")],
                           input=prompt, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=60, check=True)
            remote_command = (
                f"cd /remote/workspace && "
                f"FRONTIER_PROXY_TOKEN={q(proxy_token or '')} "
                f"FRONTIER_PROXY_URL=http://127.0.0.1:{proxy_port} "
                f"/remote/workspace -p \"$(cat {q(remote_prompt)})\" "
                f"--model {q(model)} --effort {q(effort)} --dangerously-skip-permissions "
                "--allowedTools Bash --disallowedTools WebSearch,WebFetch,Read,Edit,Write,Glob,Grep "
                "--output-format stream-json --verbose --no-session-persistence"
            )
            proc = subprocess.run(["ssh", claude_host, "bash", "-lc", repr(remote_command)],
                                  text=True, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            subprocess.run(["ssh", claude_host, "rm", "-f", remote_prompt],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        elif agent == "claude":
            with tempfile.TemporaryDirectory(prefix="rsd-frontier-empty-") as cwd:
                proc = subprocess.run([
                    "claude", "-p", prompt, "--model", model, "--effort", effort,
                    "--dangerously-skip-permissions", "--allowedTools", "Bash",
                    "--disallowedTools", "WebSearch,WebFetch,Read,Edit,Write,Glob,Grep",
                    "--output-format", "stream-json", "--verbose", "--no-session-persistence",
                ], cwd=cwd, text=True, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
        elif agent == "codex":
            with tempfile.TemporaryDirectory(prefix="rsd-frontier-empty-") as cwd:
                proc = subprocess.run([
                    CODEX_BIN, "exec", "--ignore-user-config", "--ignore-rules",
                    "--ephemeral", "--skip-git-repo-check", "-C", cwd,
                    "--dangerously-bypass-approvals-and-sandbox", "--json",
                    "-m", model, "-c", f'model_reasoning_effort="{effort}"', prompt,
                ], text=True, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
        else:
            raise ValueError(f"unsupported agent: {agent}")
    return proc.returncode


def numstat(output: str) -> dict:
    added = removed = files = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            added += int(parts[0]); removed += int(parts[1]); files += 1
    return {"files": files, "added": added, "removed": removed}


def execute_recovery(pair: dict, metadata: dict, replay_spec: dict, agent: str, model: str,
                     effort: str, output_dir: Path, timeout: int, claude_host: str | None,
                     proxy_token: str | None, proxy_port: int, max_rounds: int,
                     run_future: bool = True) -> dict:
    future, current = pair["future"], pair["current"]
    image = future["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", future["instance_id"])
    stem += "-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", metadata["candidate_id"])
    container = f"rsd-frontier-{stem}-rec-{uuid.uuid4().hex[:6]}"
    row = {"anchor_id": pair["anchor_id"], "pair_id": pair["pair_id"], "agent": agent,
           "model": model, "effort": effort, "container": container,
           "started_at": time.time(), "protocol": "agent_mediated_conflict_recovery",
           "max_recovery_rounds": max_rounds, "recovery_rounds": [], **metadata}
    setup = ssh(f"""
set -e
docker create --name {q(container)} {q(image)} sleep infinity >/dev/null
docker start {q(container)} >/dev/null
wd=$(docker inspect -f '{{{{.Config.WorkingDir}}}}' {q(container)})
if [ ! -d \"$wd/.git\" ]; then
  gitdir=$(docker exec {q(container)} bash -lc 'find / -maxdepth 4 -type d -name .git 2>/dev/null | head -1')
  wd=${{gitdir%/.git}}
fi
docker network disconnect bridge {q(container)}
printf '%s\n' \"$wd\"
""")
    row["setup"] = setup
    if setup["returncode"]:
        row["fatal"] = "setup_failed"
        row["cleanup"] = ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n")
        return row
    root = setup["output"].strip().splitlines()[-1]
    workdir = REPLAY_WORKDIR
    agent_proxy = ("/remote/workspace"
                   if claude_host else str(PROXY))
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        current_base = replay_spec["current_base"]
        future_base = replay_spec["future_base"]
        integration = replay_spec["integration_commit"]
        row["replay_worktree"] = proxy(
            "shell", container, root,
            command=f"git worktree add --detach {q(workdir)} {q(current_base)}")
        if row["replay_worktree"]["returncode"]:
            row["fatal"] = "replay_worktree_failed"
            return row
        with tempfile.TemporaryDirectory(prefix="rsd-replay-state-") as tmp:
            candidate_patch = Path(tmp) / "candidate.patch"
            candidate_patch.write_text(replay_spec["candidate_patch"])
            row["replay_candidate_apply"] = proxy("apply", container, workdir, patch=candidate_patch)
        if row["replay_candidate_apply"]["returncode"]:
            row["fatal"] = "replay_candidate_apply_failed"
            return row
        row["replay_candidate_commit"] = proxy(
            "shell", container, workdir,
            command=f"git add -A && git {GIT_ID} commit -m 'frozen alternative T1 state' >/dev/null")

        # ---- replay with agent-mediated recovery -------------------------------------------
        resume_after = None
        metadata_conflicts: list[dict] = []
        replay_started = time.time()
        row["replay_success"] = False
        while True:
            replay = proxy("shell", container, workdir,
                           command=replay_script(current_base, future_base, integration, resume_after),
                           timeout=1200)
            metadata_conflicts += [
                {"commit": c, "files": f.split()}
                for c, f in re.findall(r"RSD_METADATA_CONFLICT=([0-9a-f]+):([^\n]*)", replay["output"])]
            hard = re.search(r"RSD_CODE_CONFLICT=([0-9a-f]+):([^\n]*)", replay["output"])
            if replay["returncode"] == 0:
                row["replay_success"] = True
                row["final_replay"] = replay
                break
            if replay["returncode"] != 42 or not hard:
                row["final_replay"] = replay
                row["fatal"] = "sequential_replay_error"
                return row
            commit, files = hard.group(1), hard.group(2).split()
            round_index = len(row["recovery_rounds"])
            if round_index >= max_rounds:
                row["final_replay"] = replay
                row["fatal"] = "recovery_rounds_exhausted"
                row["unresolved_conflict"] = {"commit": commit, "files": files}
                return row
            subject = proxy("shell", container, workdir,
                            command=f"git log -1 --format=%s {q(commit)}")["output"].strip()
            upstream = proxy("shell", container, workdir,
                             command=f"git show --numstat --format= {q(commit)}")
            rec = {"round": round_index, "conflict_commit": commit, "conflict_files": files,
                   "upstream_subject": subject[:200], "upstream_numstat": numstat(upstream["output"]),
                   "started_at": time.time()}
            log = output_dir / f"{stem}_recovery{round_index}.stream.jsonl"
            prompt = recovery_prompt(agent_proxy, container, workdir, pair["repo"], commit, files, subject)
            rec["agent_returncode"] = run_agent(agent, model, effort, prompt, log, timeout,
                                               claude_host, proxy_token, proxy_port, container,
                                               f"recovery{round_index}")
            rec["consumer"] = parse_stream(log)
            # Harness verification: nothing unmerged, no markers, cherry-pick concluded.
            # Conflict markers are checked only in the files git reported as unmerged;
            # a repository-wide '=======' scan matches reStructuredText underlines.
            marker_files = " ".join(q(f) for f in files)
            check = proxy("shell", container, workdir, command=(
                "unmerged=$(git diff --name-only --diff-filter=U); "
                "echo \"RSD_UNMERGED=$unmerged\"; "
                f"markers=$(grep -l -E '^(<<<<<<< |>>>>>>> |\\|\\|\\|\\|\\|\\|\\| )' -- {marker_files} 2>/dev/null | tr '\\n' ' '); "
                "echo \"RSD_MARKERS=$markers\"; "
                "if [ -f \"$(git rev-parse --git-path CHERRY_PICK_HEAD)\" ]; then echo RSD_CP_INPROGRESS=1; else echo RSD_CP_INPROGRESS=0; fi; "
                "git status --short | head -50"))
            rec["verification"] = check
            unmerged = re.search(r"RSD_UNMERGED=(.*)", check["output"])
            markers = re.search(r"RSD_MARKERS=(.*)", check["output"])
            in_progress = "RSD_CP_INPROGRESS=1" in check["output"]
            if (unmerged and unmerged.group(1).strip()) or (markers and markers.group(1).strip()):
                rec["resolved"] = False
                rec["finished_at"] = time.time(); rec["seconds"] = rec["finished_at"] - rec["started_at"]
                row["recovery_rounds"].append(rec)
                row["fatal"] = "recovery_unresolved"
                row["unresolved_conflict"] = {"commit": commit, "files": files}
                return row
            if in_progress:
                cont = proxy("shell", container, workdir, command=(
                    f"git add -A && GIT_EDITOR=true git {GIT_ID} cherry-pick --continue"))
                rec["harness_continue"] = cont
                if cont["returncode"]:
                    rec["resolved"] = False
                    rec["finished_at"] = time.time(); rec["seconds"] = rec["finished_at"] - rec["started_at"]
                    row["recovery_rounds"].append(rec)
                    row["fatal"] = "recovery_continue_failed"
                    row["unresolved_conflict"] = {"commit": commit, "files": files}
                    return row
            resolution = proxy("shell", container, workdir,
                               command="git diff --numstat HEAD~1 HEAD && git log -1 --format=%H")
            rec["resolution_numstat"] = numstat(resolution["output"])
            rec["resolution_head"] = resolution["output"].strip().splitlines()[-1] if resolution["output"].strip() else None
            rec["resolved"] = True
            rec["finished_at"] = time.time(); rec["seconds"] = rec["finished_at"] - rec["started_at"]
            row["recovery_rounds"].append(rec)
            resume_after = commit
        row["metadata_conflicts"] = metadata_conflicts
        row["replay_seconds"] = time.time() - replay_started
        row["recovery_tool_calls"] = sum(r["consumer"]["tool_calls"] for r in row["recovery_rounds"])
        row["recovery_agent_seconds"] = sum(r["seconds"] for r in row["recovery_rounds"])
        row["recovery_success"] = True

        # ---- verified recovery diagnostic: prior task still passes on the recovered tree ----
        prior_paths = patch_paths(current.get("test_patch", ""))
        if current.get("FAIL_TO_PASS") and current.get("test_patch"):
            with tempfile.TemporaryDirectory(prefix="rsd-prior-tests-") as tmp:
                prior_patch = Path(tmp) / "prior-tests.patch"
                prior_patch.write_text(current["test_patch"])
                row["recovery_prior_test_apply"] = proxy("apply", container, workdir, patch=prior_patch)
            if row["recovery_prior_test_apply"]["returncode"] == 0:
                row["recovery_prior_task_test"] = run_pytest(
                    (container, workdir), current.get("FAIL_TO_PASS", []),
                    current.get("test_patch", ""), timeout=1800)
            restore = "; ".join(
                f"if git cat-file -e HEAD:{q(p)} 2>/dev/null; then git show HEAD:{q(p)} > {q(p)}; else rm -f {q(p)}; fi"
                for p in prior_paths) or "true"
            row["recovery_prior_test_restore"] = proxy("shell", container, workdir, command=restore)
        row["verified_recovery"] = bool(
            row["recovery_success"] and (
                not current.get("FAIL_TO_PASS")
                or row.get("recovery_prior_task_test", {}).get("returncode") == 0))

        # A recovery-budget sweep estimates the recovery CDF and its cost from
        # independent restarts.  It deliberately stops here so that every
        # budget receives the same recovery-only workload; future-task
        # continuation can be evaluated later on a pre-registered endpoint.
        if not run_future:
            row["future_evaluation_skipped"] = True
            return row

        # ---- unchanged future-task consumer session and strict evaluation ------------------
        row["initial_status"] = proxy("status", container, workdir)
        log = output_dir / f"{stem}_future.stream.jsonl"
        prompt = future_prompt(agent_proxy, container, workdir, pair["repo"], future["problem_statement"])
        row["consumer_returncode"] = run_agent(agent, model, effort, prompt, log, timeout,
                                              claude_host, proxy_token, proxy_port, container, "future")
        row["consumer"] = parse_stream(log)
        row["agent_status"] = proxy("status", container, workdir)
        row["agent_diff"] = proxy("shell", container, workdir,
                                  command="git diff --stat && git diff --numstat && git diff")
        row["changed_by_agent"] = bool(row["agent_diff"]["output"].strip())
        oracle_paths = patch_paths(future.get("test_patch", ""))
        if oracle_paths:
            restore = "; ".join(
                f"if git cat-file -e HEAD:{q(path)} 2>/dev/null; then "
                f"git show HEAD:{q(path)} > {q(path)}; else rm -f {q(path)}; fi"
                for path in oracle_paths)
            row["oracle_test_restore"] = proxy("shell", container, workdir, command=restore)
        with tempfile.TemporaryDirectory(prefix="rsd-frontier-tests-") as tmp:
            test_patch = Path(tmp) / "future-tests.patch"
            test_patch.write_text(future.get("test_patch", ""))
            row["hidden_test_apply"] = proxy("apply", container, workdir, patch=test_patch)
            if current.get("test_patch"):
                prior_patch = Path(tmp) / "prior-tests.patch"
                prior_patch.write_text(current["test_patch"])
                row["prior_test_apply"] = proxy("apply", container, workdir, patch=prior_patch)
        if row["hidden_test_apply"]["returncode"] == 0:
            row["successor_oracle_test"] = run_pytest(
                (container, workdir), future.get("FAIL_TO_PASS", []),
                future.get("test_patch", ""), timeout=1800)
            row["successor_regression_test"] = run_pytest(
                (container, workdir), list(future.get("PASS_TO_PASS", []))[:20],
                future.get("test_patch", ""), timeout=1800)
            row["prior_task_test"] = run_pytest(
                (container, workdir), current.get("FAIL_TO_PASS", []),
                current.get("test_patch", ""), timeout=1800)
        row["prior_preserved"] = (not current.get("FAIL_TO_PASS") or
                                  row.get("prior_task_test", {}).get("returncode") == 0)
        row["success"] = bool(
            row.get("successor_oracle_test", {}).get("returncode") == 0
            and row.get("successor_regression_test", {}).get("returncode") == 0
            and row["prior_preserved"])
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
    finally:
        row["cleanup"] = ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n")
        row["finished_at"] = time.time()
        row["seconds"] = row["finished_at"] - row["started_at"]
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--futures", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--replay-protocol", required=True, type=Path)
    parser.add_argument("--conflict-arms", required=True, type=Path,
                        help="Frozen list of (future_pair_id, candidate_id) arms to recover.")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--logs", required=True, type=Path)
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--claude-host")
    parser.add_argument("--proxy-port", type=int, default=18802)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--limit", type=int, help="Pilot: run only the first N arms.")
    args = parser.parse_args()

    pairs = {row["pair_id"]: row for row in read_jsonl(args.futures)}
    candidates = {row["candidate_hash"]: row for row in read_jsonl(args.candidates)}
    selection = json.loads(args.selection.read_text())
    replay_protocol = json.loads(args.replay_protocol.read_text())
    arms = json.loads(args.conflict_arms.read_text())["arms"]
    previous = read_jsonl(args.output) if args.output.exists() else []
    done = {(row.get("future_pair_id"), row.get("candidate_id")) for row in previous}
    jobs = []
    for arm in arms:
        if (arm["future_pair_id"], arm["candidate_id"]) in done:
            continue
        chosen = selection["anchors"][arm["anchor_id"]]
        level = arm["state_level"]
        candidate = candidates[chosen[f"{level}_candidate_hash"]]
        assert f"cand_{candidate['candidate_hash'][:12]}" == arm["candidate_id"]
        pair = pairs[arm["future_pair_id"]]
        metadata = {
            "future_pair_id": arm["future_pair_id"], "candidate_id": arm["candidate_id"],
            "candidate_hash": candidate["candidate_hash"], "candidate_sample": candidate.get("sample"),
            "state_level": level, "evaluation_split": "heldout_recovery",
            "strict_conflict_commit": arm.get("replay_conflict_commit"),
        }
        replay_spec = {
            "current_base": pair["current"]["base_commit"],
            "future_base": pair["future"]["base_commit"],
            "integration_commit": replay_protocol["integration_commits"][arm["anchor_id"]],
            "candidate_patch": candidate["candidate_patch"],
        }
        jobs.append((pair, metadata, replay_spec))
    if args.limit:
        jobs = jobs[:args.limit]

    if args.claude_host and args.agent != "claude":
        raise SystemExit("--claude-host is valid only with --agent claude")
    if args.agent == "claude" and not args.claude_host:
        raise SystemExit("remote Claude replication requires --claude-host")
    proxy_token = uuid.uuid4().hex if args.claude_host else None
    tunnel = None
    if args.claude_host:
        threading.Thread(target=serve, args=(args.proxy_port, proxy_token), daemon=True).start()
        tunnel = subprocess.Popen([
            "ssh", "-N", "-o", "ExitOnForwardFailure=yes",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-R", f"127.0.0.1:{args.proxy_port}:127.0.0.1:{args.proxy_port}", args.claude_host,
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2)
        if tunnel.poll() is not None:
            detail = tunnel.stdout.read().decode(errors="replace") if tunnel.stdout else ""
            raise SystemExit(f"reverse tunnel failed to start: {detail[-2000:]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("a") as handle:
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
                pending = [pool.submit(
                    execute_recovery, pair, metadata, replay_spec, args.agent, args.model,
                    args.effort, args.logs, args.timeout, args.claude_host, proxy_token,
                    args.proxy_port, args.max_rounds,
                ) for pair, metadata, replay_spec in jobs]
                for future in concurrent.futures.as_completed(pending):
                    row = future.result()
                    handle.write(json.dumps(row) + "\n")
                    handle.flush()
                    print(json.dumps({
                        "anchor": row.get("anchor_id"), "future": row.get("future_pair_id"),
                        "state": row.get("state_level"), "rounds": len(row.get("recovery_rounds", [])),
                        "recovered": row.get("recovery_success"),
                        "verified": row.get("verified_recovery"),
                        "success": row.get("success"), "fatal": row.get("fatal"),
                        "seconds": round(row.get("seconds", 0)),
                    }), flush=True)
    finally:
        if tunnel is not None:
            tunnel.terminate()
            tunnel.wait(timeout=10)


if __name__ == "__main__":
    main()
