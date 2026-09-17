#!/usr/bin/env python3
"""Calibrate a local Claude Code frontier consumer against frozen audit controls on yury."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from frontier_proxy_server import serve


ROOT = Path(__file__).resolve().parent
PROXY = ROOT / "frontier_container_proxy.py"
PRIME = "prime/primeintellect/"
DOCKERHUB = "docker.io/swerebenchv2/"


def run(cmd: list[str], *, timeout: int = 1200, input_text: str | None = None) -> dict:
    started = time.time()
    proc = subprocess.run(cmd, input=input_text, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)
    return {"returncode": proc.returncode, "seconds": time.time() - started,
            "output": proc.stdout[-30000:]}


def ssh(script: str, *, timeout: int = 1200, input_text: str | None = None) -> dict:
    if os.environ.get("RSD_DOCKER_LOCAL") == "1":
        return run(["bash", "-s"], timeout=timeout,
                   input_text=script if input_text is None else script + "\n" + input_text)
    host = os.environ.get("RSD_DOCKER_HOST", "remote-host")
    return run(["ssh", host, "bash", "-s"], timeout=timeout,
               input_text=script if input_text is None else script + "\n" + input_text)


def q(value: str) -> str:
    return shlex.quote(value)


def proxy(action: str, container: str, workdir: str, *, command: str | None = None,
          patch: Path | None = None, timeout: int = 1200,
          three_way: bool = False) -> dict:
    cmd = [sys.executable, str(PROXY), action, "--container", container, "--workdir", workdir]
    if command is not None:
        cmd += ["--command", command]
    if patch is not None:
        cmd += ["--patch", str(patch)]
    if three_way:
        cmd += ["--three-way"]
    return run(cmd, timeout=timeout)


def pytest_command(nodes: list[str]) -> str:
    return ("pytest --no-header -rA --tb=line --color=no -p no:cacheprovider "
            "-W ignore::DeprecationWarning " + " ".join(q(x) for x in nodes))


def patch_paths(patch: str) -> list[str]:
    return sorted(set(re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)))


def run_pytest(proxy_args: tuple[str, str], nodes: list[str], test_patch: str,
               *, timeout: int = 1800) -> dict:
    container, workdir = proxy_args
    result = proxy("shell", container, workdir, command=pytest_command(nodes), timeout=timeout)
    if result.get("returncode") != 4:
        return result
    files = [path for path in patch_paths(test_patch) if "test" in path.lower()]
    if not files:
        return result
    fallback = proxy(
        "shell", container, workdir,
        command=("pytest --no-header -q --tb=line --color=no -p no:cacheprovider "
                 + " ".join(q(path) for path in files)), timeout=timeout,
    )
    fallback["node_attempt"] = result
    fallback["fallback"] = "test_patch_files"
    return fallback


def parse_stream(path: Path) -> dict:
    tool_calls = invalid = 0
    final = ""
    for line in path.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") == "assistant":
            for block in row.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls += 1
        if row.get("type") == "result":
            final = row.get("result", "") or ""
            if row.get("is_error"):
                invalid += 1
        # Codex JSONL: count each command once, at start; capture the last
        # assistant message. Command failures are not protocol-invalid actions.
        item = row.get("item", {})
        if row.get("type") == "item.started" and item.get("type") in {
            "command_execution", "mcp_tool_call", "dynamic_tool_call"
        }:
            tool_calls += 1
        if row.get("type") == "item.completed" and item.get("type") == "agent_message":
            final = item.get("text", "") or ""
        if row.get("type") == "turn.failed":
            invalid += 1
    return {"tool_calls": tool_calls, "invalid_actions": invalid, "final": final[-4000:]}


def execute_one(pair: dict, session_index: int, agent: str, model: str, effort: str,
                output_dir: Path, timeout: int, claude_host: str | None,
                proxy_token: str | None, proxy_port: int,
                initial_delta: Path | None = None, metadata: dict | None = None,
                replay_spec: dict | None = None) -> dict:
    future, current = pair["future"], pair["current"]
    image = future["image_name"]
    if image.startswith(PRIME):
        image = DOCKERHUB + image[len(PRIME):]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", future["instance_id"])
    if metadata and metadata.get("candidate_id"):
        stem += "-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", metadata["candidate_id"])
    container = f"rsd-frontier-{stem}-{session_index}-{uuid.uuid4().hex[:6]}"
    row = {"anchor_id": pair["anchor_id"], "pair_id": pair["pair_id"],
           "session_index": session_index, "agent": agent,
           "model": model, "effort": effort,
           "container": container, "started_at": time.time()}
    if metadata:
        row.update(metadata)
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
    workdir = setup["output"].strip().splitlines()[-1]
    row["workdir"] = workdir
    try:
        if replay_spec is not None:
            replay_workdir = "/tmp/rsd-sequential-replay"
            current_base = replay_spec["current_base"]
            future_base = replay_spec["future_base"]
            integration = replay_spec["integration_commit"]
            row["replay_worktree"] = proxy(
                "shell", container, workdir,
                command=f"git worktree add --detach {q(replay_workdir)} {q(current_base)}",
            )
            if row["replay_worktree"]["returncode"]:
                row["fatal"] = "replay_worktree_failed"
                return row
            with tempfile.TemporaryDirectory(prefix="rsd-replay-state-") as tmp:
                candidate_patch = Path(tmp) / "candidate.patch"
                candidate_patch.write_text(replay_spec["candidate_patch"])
                row["replay_candidate_apply"] = proxy(
                    "apply", container, replay_workdir, patch=candidate_patch
                )
            if row["replay_candidate_apply"]["returncode"]:
                row["fatal"] = "replay_candidate_apply_failed"
                return row
            row["replay_candidate_commit"] = proxy(
                "shell", container, replay_workdir,
                command=("git add -A && git -c user.name=RSD -c user.email=rsd@invalid "
                         "commit -m 'frozen alternative T1 state' >/dev/null"),
            )
            replay_command = f"""
set -e
applied=0
empty=0
metadata_conflicts=0
for commit in $(git rev-list --first-parent --reverse {q(current_base)}..{q(future_base)}); do
  if [ "$commit" = {q(integration)} ]; then continue; fi
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
          git show "$commit:$path" > "$path"; git add "$path"
        else
          rm -f "$path"; git add -u -- "$path"
        fi
      done
      git -c user.name=RSD -c user.email=rsd@invalid cherry-pick --continue >/tmp/replay-continue.log 2>&1
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
            row["sequential_replay"] = proxy(
                "shell", container, replay_workdir, command=replay_command, timeout=1200
            )
            row["replay_success"] = row["sequential_replay"]["returncode"] == 0
            metadata_matches = re.findall(
                r"RSD_METADATA_CONFLICT=([0-9a-f]+):([^\n]*)",
                row["sequential_replay"]["output"],
            )
            row["metadata_conflicts"] = [
                {"commit": commit, "files": files.split()}
                for commit, files in metadata_matches
            ]
            hard = re.search(r"RSD_CODE_CONFLICT=([0-9a-f]+):([^\n]*)",
                             row["sequential_replay"]["output"])
            if hard:
                row["replay_conflict_commit"] = hard.group(1)
                row["replay_conflict_files"] = hard.group(2).split()
            if not row["replay_success"]:
                row["fatal"] = "sequential_replay_failed"
                return row
            workdir = replay_workdir
            row["workdir"] = workdir
        if initial_delta is not None:
            row["state_apply"] = proxy(
                "apply", container, workdir, patch=initial_delta, three_way=True
            )
            if row["state_apply"]["returncode"]:
                row["fatal"] = "state_apply_failed"
                return row
        row["initial_status"] = proxy("status", container, workdir)
        if claude_host:
            agent_proxy = "/remote/workspace"
        else:
            agent_proxy = str(PROXY)
        prompt = f"""You are the future software-engineering consumer in a frozen research evaluation.
Solve the issue below in the isolated Docker repository. Hidden evaluation tests are not available to you.
Do not use the internet, git history, git reset, or git checkout. Preserve prior behavior and keep edits minimal.

You may operate ONLY through these commands:
- Inspect or test: python3 {agent_proxy} shell --container {container} --workdir {workdir} --command '<shell command>'
- Apply an edit: write a unified diff to /tmp/{container}.patch, then run python3 {agent_proxy} apply --container {container} --workdir {workdir} --patch /tmp/{container}.patch
- Check final state: python3 {agent_proxy} status --container {container} --workdir {workdir}

Do not inspect any local workspace files. First inspect the relevant implementation, reproduce when practical,
then edit and test. End only when the repository implementation is ready.

Repository: {pair['repo']}
Issue:
{future['problem_statement']}
"""
        output_dir.mkdir(parents=True, exist_ok=True)
        log = output_dir / f"{stem}_session{session_index}.stream.jsonl"
        with log.open("w") as handle:
            if agent == "claude" and claude_host:
                remote_prompt = f"/tmp/{container}.prompt"
                subprocess.run(["ssh", claude_host, "bash", "-lc",
                                repr(f"cat > {remote_prompt}")], input=prompt, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=True)
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
                        "codex", "exec", "--ignore-user-config", "--ignore-rules",
                        "--ephemeral", "--skip-git-repo-check", "-C", cwd,
                        "--dangerously-bypass-approvals-and-sandbox", "--json",
                        "-m", model, "-c", f'model_reasoning_effort="{effort}"', prompt,
                    ], text=True, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
            else:
                raise ValueError(f"unsupported agent: {agent}")
        row["consumer_returncode"] = proc.returncode
        row["consumer"] = parse_stream(log)
        row["agent_status"] = proxy("status", container, workdir)
        row["agent_diff"] = proxy("shell", container, workdir,
                                  command="git diff --stat && git diff --numstat && git diff")
        row["changed_by_agent"] = bool(row["agent_diff"]["output"].strip())

        # The benchmark owns oracle-test files.  A consumer may legitimately
        # update a public test alongside production code; restore only files
        # targeted by the hidden test patch before installing that patch.
        oracle_paths = patch_paths(future.get("test_patch", ""))
        if oracle_paths:
            restore = "; ".join(
                f"if git cat-file -e HEAD:{q(path)} 2>/dev/null; then "
                f"git show HEAD:{q(path)} > {q(path)}; else rm -f {q(path)}; fi"
                for path in oracle_paths
            )
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
            and row["prior_preserved"]
        )
    except Exception as exc:
        row["fatal"] = f"{type(exc).__name__}:{exc}"
    finally:
        row["cleanup"] = ssh(f"docker rm -f {q(container)} >/dev/null 2>&1 || true\n")
    row["finished_at"] = time.time()
    row["seconds"] = row["finished_at"] - row["started_at"]
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchors", required=True, type=Path)
    parser.add_argument("--futures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--logs", required=True, type=Path)
    parser.add_argument("--model", default="opus")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--agent", choices=["claude", "codex"], default="claude")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--anchor-indices", nargs="+", type=int)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--claude-host", help="Run the authenticated Claude CLI on this SSH host.")
    parser.add_argument("--proxy-port", type=int, default=18765)
    args = parser.parse_args()
    anchors = json.loads(args.anchors.read_text())
    allowed = set(args.anchor_indices) if args.anchor_indices is not None else None
    audit_ids = {a["audit_future_pair_id"] for i, a in enumerate(anchors)
                 if allowed is None or i in allowed}
    pairs = [json.loads(line) for line in args.futures.read_text().splitlines()
             if line.strip() and json.loads(line).get("pair_id") in audit_ids]
    jobs = [(pair, sample) for pair in pairs for sample in range(args.samples)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            if line.strip():
                old = json.loads(line)
                done.add((old.get("pair_id"), old.get("session_index")))
    jobs = [job for job in jobs if (job[0]["pair_id"], job[1]) not in done]
    proxy_token = uuid.uuid4().hex if args.claude_host else None
    tunnel = None
    if args.claude_host and args.agent != "claude":
        raise SystemExit("--claude-host is valid only with --agent claude")
    if args.claude_host:
        threading.Thread(target=serve, args=(args.proxy_port, proxy_token), daemon=True).start()
        tunnel = subprocess.Popen([
            "ssh", "-N", "-o", "ExitOnForwardFailure=yes",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-R", f"127.0.0.1:{args.proxy_port}:127.0.0.1:{args.proxy_port}", args.claude_host,
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        time.sleep(2)
        if tunnel.poll() is not None:
            detail = (tunnel.stdout.read().decode(errors="replace") if tunnel.stdout else "")
            raise SystemExit(f"reverse tunnel failed to start: {detail[-2000:]}")
    with args.output.open("a") as handle:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = [pool.submit(execute_one, pair, sample, args.agent, args.model, args.effort,
                                   args.logs, args.timeout, args.claude_host,
                                   proxy_token, args.proxy_port) for pair, sample in jobs]
            for future in concurrent.futures.as_completed(pending):
                row = future.result()
                handle.write(json.dumps(row) + "\n")
                handle.flush()
                print(json.dumps({"pair_id": row.get("pair_id"),
                                  "session": row.get("session_index"),
                                  "success": row.get("success"),
                                  "changed": row.get("changed_by_agent"),
                                  "fatal": row.get("fatal")}), flush=True)
    if tunnel is not None:
        tunnel.terminate()
        tunnel.wait(timeout=10)


if __name__ == "__main__":
    main()
