#!/usr/bin/env python3
"""Run frozen held-out continuations for continuation-aware selection v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from empirical_continuation_suite import CASES, execute, extract_code


def render(tokenizer, source: str, requirement: str) -> str:
    user = f'''You maintain a small Python module. Implement the new requirement while preserving all existing behavior.
Return ONLY the complete replacement Python module, inside one python code block. Do not return tests or explanation.

CURRENT MODULE:
```python
{source}
```

NEW REQUIREMENT:
{requirement}
'''
    messages = [
        {"role": "system", "content": "You are a precise software engineer."},
        {"role": "user", "content": user},
    ]
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    except Exception as exc:
        if "System role not supported" not in str(exc):
            raise
        return tokenizer.apply_chat_template(
            [{"role": "user", "content": "You are a precise software engineer.\n\n" + user}],
            tokenize=False,
            add_generation_prompt=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-dir", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-name", default="qwen3_coder_30b_a3b")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--load-in-8bit", action="store_true")
    parser.add_argument("--completed-from", nargs="*", type=Path, default=[])
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=1)
    args = parser.parse_args()

    protocol = json.loads((args.protocol_dir / "protocol.json").read_text())
    states = [json.loads(line) for line in (args.protocol_dir / "frozen_states.jsonl").read_text().splitlines() if line]
    tasks = json.loads((args.protocol_dir / "frozen_heldout_tasks.json").read_text())
    repeats = int(protocol["repeats"])
    base_seeds = list(protocol["seeds"])
    if len(base_seeds) != repeats:
        raise RuntimeError("Protocol seed count does not equal repeats")

    jobs = []
    for state in states:
        for future_id, requirement, hidden_test in tasks[state["family"]]:
            for repeat in range(repeats):
                jobs.append((state, future_id, requirement, hidden_test, repeat))
    jobs.sort(key=lambda x: (x[0]["family"], x[0]["state_sha256"], x[1], x[4]))
    jobs = [job for index, job in enumerate(jobs) if index % args.num_shards == args.shard_index]
    jobs = list(enumerate(jobs))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    for completed_path in [args.output, *args.completed_from]:
        if not completed_path.exists():
            continue
        for line in completed_path.read_text().splitlines():
            try:
                row = json.loads(line)
                done.add((row["consumer"], row["family"], row["state_sha256"], row["future_id"], row["repeat"]))
            except Exception:
                pass
    jobs = [
        (shard_position, job)
        for shard_position, job in jobs
        if shard_position % args.num_workers == args.worker_index
        and (args.model_name, job[0]["family"], job[0]["state_sha256"], job[1], job[4]) not in done
    ]

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    tokenizer.padding_side = "left"
    model_kwargs = {"torch_dtype": "auto", "device_map": "auto", "trust_remote_code": True,
                    "local_files_only": True}
    if args.load_in_8bit:
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    model = AutoModelForCausalLM.from_pretrained(args.model, **model_kwargs)
    model.eval()

    with args.output.open("a", encoding="utf-8") as handle:
        for start in range(0, len(jobs), args.batch_size):
            indexed_batch = jobs[start:start + args.batch_size]
            batch = [item[1] for item in indexed_batch]
            prompts = [render(tokenizer, item[0]["source"], item[2]) for item in batch]
            inputs = tokenizer(prompts, return_tensors="pt", padding=True).to(model.device)
            job_seed = base_seeds[batch[0][4]] + int(batch[0][0]["state_sha256"][:8], 16) + indexed_batch[0][0]
            torch.manual_seed(job_seed)
            begin = time.perf_counter()
            with torch.no_grad():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=int(protocol["max_new_tokens"]),
                    do_sample=True,
                    temperature=float(protocol["temperature"]),
                    top_p=float(protocol["top_p"]),
                    pad_token_id=tokenizer.eos_token_id,
                    use_cache=True,
                )
            elapsed = (time.perf_counter() - begin) / len(batch)
            for index, (state, future_id, _requirement, hidden_test, repeat) in enumerate(batch):
                new_tokens = generated[index, inputs.input_ids.shape[1]:]
                raw = tokenizer.decode(new_tokens, skip_special_tokens=True)
                code = extract_code(raw)
                current_test = CASES[state["family"]]["current"]
                current = execute(code, current_test)
                joint = execute(code, current_test + "\n" + hidden_test)
                row = {
                    "protocol": protocol["protocol"],
                    "consumer": args.model_name,
                    "family": state["family"],
                    "state_sha256": state["state_sha256"],
                    "future_id": future_id,
                    "repeat": repeat,
                    "seed": job_seed,
                    "current_preserved": current["success"],
                    "future_success": joint["success"],
                    "returncode": joint["returncode"],
                    "stderr": joint["stderr"],
                    "generation_s": elapsed,
                    "prompt_tokens": int(inputs.attention_mask[index].sum()),
                    "completion_tokens": int(new_tokens.numel()),
                    "output_sha256": hashlib.sha256(code.encode()).hexdigest(),
                    "raw": raw,
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(json.dumps({k: row[k] for k in ("family", "state_sha256", "future_id", "repeat", "future_success")}), flush=True)


if __name__ == "__main__":
    main()
