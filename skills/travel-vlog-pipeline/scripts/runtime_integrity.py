#!/usr/bin/env python3
"""Deterministic integrity checks for pinned local runtime dependencies."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple


EXCLUDED_DIRECTORY_NAMES = {".git", "__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_tree_files(root: Path) -> Iterable[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
            continue
        if path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def directory_tree_record(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"vendor tree is missing: {root}")
    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    for path in iter_tree_files(root):
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(file_sha256(path)))
        digest.update(b"\n")
        count += 1
        total_bytes += size
    return {
        "root": str(root),
        "sha256": digest.hexdigest(),
        "file_count": count,
        "bytes": total_bytes,
    }


def forbidden_bytecode_paths(root: Path) -> List[Path]:
    """Return executable Python caches that must never exist in pinned vendor trees."""
    forbidden: List[Path] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        if ".git" in current_path.relative_to(root).parts:
            directories[:] = []
            continue
        kept_directories: List[str] = []
        for name in directories:
            candidate = current_path / name
            if name == "__pycache__":
                forbidden.append(candidate)
            else:
                kept_directories.append(name)
        directories[:] = kept_directories
        forbidden.extend(
            current_path / name
            for name in files
            if Path(name).suffix.lower() in EXCLUDED_SUFFIXES
        )
    return sorted(forbidden, key=lambda path: path.as_posix())


def is_reparse_path(path: Path) -> bool:
    try:
        junction_check = getattr(path, "is_junction", None)
        attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return path.is_symlink() or bool(callable(junction_check) and junction_check()) or bool(attributes & reparse_flag)
    except OSError:
        return True


def reparse_paths(root: Path) -> List[Path]:
    """Find links and Windows reparse points without traversing through them."""
    if is_reparse_path(root):
        return [root]
    found: List[Path] = []
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_directories: List[str] = []
        for name in directories:
            candidate = current_path / name
            if is_reparse_path(candidate):
                found.append(candidate)
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        found.extend(current_path / name for name in files if is_reparse_path(current_path / name))
    return sorted(found, key=lambda path: path.as_posix())


def installed_distribution_record() -> Dict[str, Any]:
    """Record the exact installed distribution/version set without contacting a package index."""
    items = set()
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get("Name")
        if name and dist.version:
            normalized_name = re.sub(r"[-_.]+", "-", str(name)).lower()
            items.add(f"{normalized_name}=={dist.version}")
    distributions = sorted(items)
    encoded = json.dumps(distributions, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return {"distributions": distributions, "sha256": hashlib.sha256(encoded).hexdigest()}


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        common = os.path.commonpath([str(path.resolve()), str(directory.resolve())])
        return os.path.normcase(common) == os.path.normcase(str(directory.resolve()))
    except ValueError:
        return False


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without resolving symlinks or junctions."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def lexical_path_is_within(path: Path, directory: Path) -> bool:
    """Containment check that deliberately preserves reparse-point components."""
    try:
        path_text = os.path.normcase(os.fspath(lexical_absolute(path)))
        directory_text = os.path.normcase(os.fspath(lexical_absolute(directory)))
        return os.path.commonpath([path_text, directory_text]) == directory_text
    except ValueError:
        return False


def reparse_ancestors(path: Path, stop: Path | None = None) -> List[Path]:
    """Inspect a lexical path and its parents before any call to ``resolve``."""
    current = lexical_absolute(path)
    stop_path = lexical_absolute(stop) if stop is not None else None
    found: List[Path] = []
    while True:
        if os.path.lexists(current) and is_reparse_path(current):
            found.append(current)
        if stop_path is not None and os.path.normcase(os.fspath(current)) == os.path.normcase(os.fspath(stop_path)):
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return found


def verify_vendor_lock(workspace: Path, lock_path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    workspace_lexical = lexical_absolute(workspace)
    lock_path = lock_path.resolve()
    with lock_path.open("r", encoding="utf-8-sig") as handle:
        lock = json.load(handle)
    errors: List[str] = []
    records: List[Dict[str, Any]] = []
    if lock.get("schema_version") != "travel-vlog-upstream-lock/2":
        errors.append("upstream lock schema is missing or unsupported")
    workspace_links = reparse_ancestors(workspace_lexical)
    if workspace_links:
        examples = ", ".join(str(path) for path in workspace_links[:5])
        errors.append(f"workspace path traverses a symlink, junction, or reparse point: {examples}")
        return records, errors
    vendor_root_lexical = lexical_absolute(workspace_lexical / ".vendor")
    vendor_root_links = reparse_ancestors(vendor_root_lexical, stop=workspace_lexical)
    if vendor_root_links:
        examples = ", ".join(str(path) for path in vendor_root_links[:5])
        errors.append(f"vendor root path traverses a symlink, junction, or reparse point: {examples}")
        return records, errors
    workspace_resolved = workspace_lexical.resolve()
    vendor_root = vendor_root_lexical.resolve()
    for source in lock.get("sources") or []:
        if not isinstance(source, Mapping):
            errors.append("upstream lock source entry is not an object")
            continue
        name = str(source.get("name") or "unknown")
        directory_lexical = lexical_absolute(workspace_lexical / str(source.get("local_path") or ""))
        if not lexical_path_is_within(directory_lexical, vendor_root_lexical):
            errors.append(f"vendor source escapes workspace .vendor: {name}")
            continue
        source_root_links = reparse_ancestors(directory_lexical, stop=vendor_root_lexical)
        if source_root_links:
            examples = ", ".join(str(path) for path in source_root_links[:5])
            errors.append(f"vendor source path traverses a symlink, junction, or reparse point: {name}: {examples}")
            continue
        directory = directory_lexical.resolve()
        if not path_is_within(directory, vendor_root):
            errors.append(f"vendor source escapes workspace .vendor: {name}")
            continue
        if not path_is_within(directory, workspace_resolved):
            errors.append(f"vendor source escapes workspace: {name}")
            continue
        linked = reparse_paths(directory_lexical) if os.path.lexists(directory_lexical) else []
        if linked:
            examples = ", ".join(path.relative_to(directory_lexical).as_posix() if path != directory_lexical else "." for path in linked[:5])
            errors.append(f"vendor tree contains a symlink, junction, or reparse point: {name}: {examples}")
            continue
        forbidden = forbidden_bytecode_paths(directory_lexical) if directory_lexical.is_dir() else []
        if forbidden:
            examples = ", ".join(path.relative_to(directory_lexical).as_posix() for path in forbidden[:5])
            errors.append(f"vendor tree contains forbidden Python bytecode cache: {name}: {examples}")
            continue
        try:
            record = directory_tree_record(directory_lexical)
        except OSError as exc:
            errors.append(f"vendor source is unreadable: {name}: {exc}")
            continue
        record["name"] = name
        records.append(record)
        expected_hash = str(source.get("tree_sha256") or "").lower()
        expected_count = int(source.get("tree_file_count") or 0)
        if not expected_hash or record["sha256"] != expected_hash:
            errors.append(f"vendor tree hash mismatch: {name}")
        if not expected_count or record["file_count"] != expected_count:
            errors.append(f"vendor tree file count mismatch: {name}")
    return records, errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify pinned vendor source trees")
    parser.add_argument("--workspace")
    parser.add_argument("--lock")
    parser.add_argument("--distributions", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.distributions:
        payload = installed_distribution_record()
        rendered = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0
    if not args.workspace or not args.lock:
        parser.error("--workspace and --lock are required unless --distributions is used")
    records, errors = verify_vendor_lock(Path(args.workspace), Path(args.lock))
    rendered = json.dumps({"records": records, "errors": errors}, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
