"""Code-only integrity and exposure checks. This is not a scientific result audit."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {".csv", ".xlsx", ".xls", ".parquet", ".geojson", ".shp",
                    ".dbf", ".shx", ".tif", ".tiff", ".png", ".pdf", ".docx", ".lic"}
# Directories that must not exist in a clean checkout: they hold inputs, solved
# results or scratch output on the author's machine.
DISALLOWED_ROOTS = {"data", "input", "results", "output", "tmp"}
# The manuscript tree is not distributed; the figure programs are the exception.
ALLOWED_PAPER_PREFIXES = ("paper/RCR/figure_build/",)
# Figure-input preparation scripts write their tables next to themselves.
SCRATCH_PREFIXES = ("provenance/figure_input_prep/",)


def main():
    manifest = json.loads((ROOT / "provenance/source_code_manifest.json").read_text())
    errors = []
    for record in manifest["files"]:
        p = ROOT / record["release_path"]
        actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        if actual != record["sha256"]:
            errors.append(f"Source checksum mismatch: {record['release_path']}")
    credential = re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if set(rel.parts) & {".git", ".venv", "__pycache__"} or not p.is_file():
            continue
        path = rel.as_posix()
        scratch = path.startswith(SCRATCH_PREFIXES)
        if p.is_symlink() or rel.parts[0] in DISALLOWED_ROOTS:
            errors.append(f"Not a permitted code-release file: {rel}")
            continue
        if rel.parts[0] == "paper" and not (path.startswith(ALLOWED_PAPER_PREFIXES) and p.suffix == ".py"):
            errors.append(f"Manuscript material in the code release: {rel}")
            continue
        if p.suffix.lower() in BLOCKED_SUFFIXES and not (scratch and p.suffix.lower() == ".csv"):
            errors.append(f"Not a permitted code-release file: {rel}")
            continue
        text = p.read_text(encoding="utf-8")
        if credential.search(text):
            errors.append(f"Possible credential: {rel}")
        if re.search(r"/(?:Users|home)/[A-Za-z0-9_.-]+/", text):
            errors.append(f"Personal absolute path: {rel}")
        if p.suffix == ".py":
            ast.parse(text, filename=str(rel))
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(manifest['files'])} source checksums, Python syntax and code-only exposure checks.")


if __name__ == "__main__":
    main()
