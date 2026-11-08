"""Restore and replay the frozen post-review packages from the mirror."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "review_supplements" / "index.json"

def restore(name, spec, dest):
    work = dest / name
    work.mkdir(parents=True, exist_ok=False)
    archive = work / "package.zip"
    with archive.open("wb") as out:
        for rel in spec["parts"]:
            out.write(base64.b64decode((ROOT / rel).read_bytes().strip(), validate=True))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != spec["sha256"]:
        raise ValueError(f"Supplement checksum mismatch: {name}")
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            path = Path(entry.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member {path}")
        z.extractall(work)
    return work / spec["directory"]

def replay_appendix_o(root):
    for panel in ("study", "hard"):
        work = root / panel
        expected = ["scores.csv", "results.json", "upstream_results.json"]
        if panel == "hard":
            expected.append("fixtures_results.json")
        def digests():
            return {n: hashlib.sha256((work / n).read_bytes()).hexdigest() for n in expected}
        saved = digests()
        for script in ("score.py", "supplemental.py"):
            subprocess.run([sys.executable, script], cwd=work, check=True)
        if panel == "hard":
            subprocess.run(["node", "independent_fixtures.js"], cwd=work, check=True)
        if saved != digests():
            raise ValueError(f"Appendix O replay mismatch: {panel}")
        print(f"Appendix O: {panel} reproduced archived results", flush=True)

def run(dest, replay):
    for name, spec in json.loads(INDEX.read_text()).items():
        work = restore(name, spec, dest)
        if replay:
            if name == "round5":
                replay_appendix_o(work)
            else:
                subprocess.run([sys.executable, spec["script"]], cwd=work, check=True)
        print(f"{name}: verified {spec['sha256']}", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", type=Path, help="keep the extracted packages here, without running them")
    args = parser.parse_args()
    if args.restore:
        run(args.restore, False)
    else:
        with tempfile.TemporaryDirectory(prefix="lossy-review-") as temp:
            run(Path(temp), True)
