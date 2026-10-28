#!/usr/bin/env python3
"""Repository inventory helper for the ljt-repo-architect skill."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

VENDORED_PREFIXES = (
    PurePosixPath("ops/vendor/subtitle_remover"),
    PurePosixPath("ops/injection/lib"),
    PurePosixPath("graphify-out"),
)

IGNORED_TOP = {
    "__pycache__", "data", "build", "dist", ".venv", ".pytest_cache", ".superpowers", ".git",
}

_ENTRYPOINT_FILES = {"main.py", "app.py", "app_mp.py"}
_OUTPUT_GROUPS = (
    "entrypoints", "backend", "frontend", "injection", "docs", "build", "vendored", "other",
)


def classify_path(path: PurePosixPath) -> str | None:
    parts = path.parts
    if not parts or parts[0] in IGNORED_TOP:
        return None
    for pfx in VENDORED_PREFIXES:
        if path.is_relative_to(pfx):
            return "vendored"
    if len(parts) == 1 and parts[0] in _ENTRYPOINT_FILES:
        return "entrypoints"
    top = parts[0]
    if top == "parse_tools":
        if len(parts) >= 2 and parts[1] == "frontend":
            return "frontend"
        return "backend"
    if top == "ops":
        if len(parts) >= 2 and parts[1] == "injection":
            return "injection"
        if len(parts) >= 2 and parts[1] == "docs":
            return "docs"
        if len(parts) >= 2 and parts[1] in {"packaging", "deploy", "scripts", "skills", "automation", "vendor"}:
            return "build" if parts[1] != "vendor" else "vendored"
        return "build"
    if top in {".github", "tests"}:
        return "build"
    return "other"


def list_files(root: Path) -> list[str]:
    try:
        out = subprocess.check_output(["git", "ls-files", "-z"], cwd=str(root), stderr=subprocess.DEVNULL)
        files = [p for p in out.decode("utf-8", errors="replace").split("\0") if p]
        if files:
            return sorted(files)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_TOP and not d.startswith(".")]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            files.append(rel.replace("\\", "/"))
    return sorted(files)


def build_inventory(root: Path) -> dict:
    tracked = list_files(root)
    groups = {g: [] for g in _OUTPUT_GROUPS}
    for rel in tracked:
        if rel.startswith("graphify-out/"):
            continue
        group = classify_path(PurePosixPath(rel))
        if group is None:
            continue
        groups[group].append(rel)
    for g in groups:
        groups[g] = sorted(groups[g])
    return {"root": str(root.resolve()), "tracked_files": tracked, "groups": groups}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = build_inventory(Path(args.root).resolve())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        for name, files in data["groups"].items():
            print(f"[{name}] {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
