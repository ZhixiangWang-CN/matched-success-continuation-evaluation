#!/usr/bin/env python3
"""Verify frozen checksums and reject credentials or author-identifying paths."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / "SHA256SUMS.txt"
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonl", ".csv", ".tex", ".yml", ".yaml"}
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{30,}"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "author home path": re.compile(
        r"/(?:Users|home|home2)/(?:" + "zhi" + r"xiangwang|" + "fby" + r"1501)(?:/|\b)", re.I
    ),
    "author identifier": re.compile(r"\b(?:" + "zhi" + r"xiangwang|" + "fby" + r"1501)\b", re.I),
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_frozen_checksums() -> int:
    checked = 0
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = ROOT / relative.strip()
        if not path.is_file():
            raise AssertionError(f"missing frozen artifact: {relative}")
        actual = digest(path)
        if actual != expected:
            raise AssertionError(f"checksum mismatch: {relative}")
        checked += 1
    return checked


def scan_text() -> int:
    scanned = 0
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{path.relative_to(ROOT)}: {label}")
        scanned += 1
    if failures:
        raise AssertionError("privacy/secret scan failed:\n" + "\n".join(failures[:50]))
    return scanned


def main() -> None:
    frozen = verify_frozen_checksums()
    scanned = scan_text()
    print(f"RELEASE_INTEGRITY_OK frozen_files={frozen} scanned_text_files={scanned}")


if __name__ == "__main__":
    main()
