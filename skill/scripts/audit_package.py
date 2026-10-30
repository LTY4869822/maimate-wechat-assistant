"""Audit a shareable skill tree; never scan the user's runtime directories."""

import argparse
import hashlib
import json
import re
from pathlib import Path

DENIED_NAMES = {
    "local-credentials.json",
    "selected-group.json",
    "installation.json",
    "config.toml",
    ".env",
    "minimax-credentials.json",
}
DENIED_PARTS = {
    ".venv",
    "__pycache__",
    ".git",
    "logs",
    "backups",
    "diagnostics",
    ".pytest_cache",
    ".ruff_cache",
}


def audit(root: Path) -> list[dict]:
    entries, problems = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if (
            path.name in DENIED_NAMES
            or set(rel.parts) & DENIED_PARTS
            or path.suffix.lower() in {".db", ".sqlite", ".log", ".mp3", ".wav", ".pyc"}
        ):
            problems.append(rel.as_posix() + ": runtime/private artifact")
        data = path.read_bytes()
        if re.search(rb"sk-[A-Za-z0-9_-]{24,}", data):
            problems.append(rel.as_posix() + ": possible API key")
        if re.search(
            rb"[A-Za-z]:[\\/]Users[\\/](?!<|YOUR_|username|user[\\/])[^\r\n<>\"']{2,}",
            data,
            re.I,
        ):
            problems.append(rel.as_posix() + ": machine-specific user path")
        if path.name != "bundle-manifest.json":
            entries.append(
                {
                    "path": rel.as_posix(),
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    if problems:
        raise ValueError("\n".join(problems))
    return entries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    entries = audit(args.root.resolve())
    manifest = args.root / "bundle-manifest.json"
    if args.write_manifest:
        manifest.write_text(
            json.dumps({"files": entries}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif (
        manifest.exists()
        and json.loads(manifest.read_text(encoding="utf-8"))["files"] != entries
    ):
        raise SystemExit("Bundle integrity manifest differs from the current files")
    print(
        f"Shareable skill audit passed: {len(entries)} files; no runtime data or apparent credentials."
    )
