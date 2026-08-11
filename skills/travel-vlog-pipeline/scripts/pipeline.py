#!/usr/bin/env python3
"""Windows-safe orchestration for the fused Travel Vlog Pipeline."""

from __future__ import annotations

import argparse
import copy
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from runtime_integrity import directory_tree_record, installed_distribution_record, verify_vendor_lock
from vlog_core import (
    ANALYSIS_VERSION,
    ContractError,
    backup_json,
    build_story_plan,
    classify_analysis,
    compile_story,
    file_sha256,
    load_json,
    load_profile,
    normalize_analysis,
    plan_missing_groups,
    story_plan_sha256,
    utc_now,
    validate_story_approval,
    write_json,
)


if os.name == "nt":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".flv"}


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def find_workspace_root() -> Optional[Path]:
    explicit = os.environ.get("TRAVEL_VLOG_WORKSPACE")
    if explicit:
        candidate = Path(os.path.abspath(os.fspath(Path(explicit).expanduser())))
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / ".vendor" / "video-editing-skill-main").is_dir():
            return parent
    return None


def require_workspace_root() -> Path:
    root = find_workspace_root()
    if root is None:
        raise RuntimeError("could not locate workspace containing .vendor/video-editing-skill-main")
    return root


def vendor_paths(root: Path) -> Tuple[Path, Path]:
    return (
        root / ".vendor" / "video-editing-skill-main",
        root / ".vendor" / "ai-video-editing-skill-main",
    )


def find_ffmpeg_tools(root: Optional[Path] = None) -> Tuple[Optional[Path], Optional[Path]]:
    candidates: List[Path] = []
    explicit = os.environ.get("TRAVEL_VLOG_FFMPEG_BIN")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if root:
        candidates.append(root / ".tools" / "ffmpeg" / "bin")
        tools_root = root / ".tools" / "ffmpeg"
        if tools_root.is_dir():
            candidates.extend(path for path in tools_root.glob("**/bin") if path.is_dir())
    for directory in candidates:
        ffmpeg = directory / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        ffprobe = directory / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ffmpeg.is_file() and ffprobe.is_file():
            return ffmpeg.resolve(), ffprobe.resolve()
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    return (Path(ffmpeg_path).resolve() if ffmpeg_path else None, Path(ffprobe_path).resolve() if ffprobe_path else None)


def find_cjk_font() -> Optional[Path]:
    """Return a local CJK font so rendering never needs a network font download."""
    explicit = os.environ.get("TRAVEL_VLOG_FONT")
    candidates: List[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    windows_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates.extend(
        windows_dir / "Fonts" / filename
        for filename in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "simsun.ttc")
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def tool_environment(root: Optional[Path] = None) -> Dict[str, str]:
    env = os.environ.copy()
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT", "PYTHONPYCACHEPREFIX"):
        env.pop(variable, None)
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg:
        env["PATH"] = str(ffmpeg.parent) + os.pathsep + env.get("PATH", "")
    env.setdefault("PYTHONUTF8", "1")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_command(
    command: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    root: Optional[Path] = None,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        env=tool_environment(root),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip()
        raise RuntimeError(f"command exited {result.returncode}: {detail}")
    return result


def upstream_script(root: Path, source: str, name: str) -> Path:
    maxazure, vlog = vendor_paths(root)
    base = maxazure if source == "maxazure" else vlog
    path = base / "scripts" / name
    if not path.is_file():
        raise RuntimeError(f"upstream script is missing: {path}")
    return path


def run_upstream(
    root: Path,
    source: str,
    name: str,
    args: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    require_runtime_integrity(root)
    return run_command(
        [sys.executable, "-X", "utf8", "-s", "-B", str(upstream_script(root, source, name)), *[str(item) for item in args]],
        cwd=cwd or root,
        root=root,
        capture=capture,
        check=check,
    )


def parse_fps(value: Any) -> float:
    text = str(value or "0")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            return float(numerator) / denominator_value if denominator_value else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe_media(path: Path, root: Path) -> Dict[str, Any]:
    _, ffprobe = find_ffmpeg_tools(root)
    if ffprobe is None:
        raise RuntimeError("ffprobe is not available")
    result = run_command(
        [
            str(ffprobe), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        root=root,
        capture=True,
        check=True,
    )
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration_values = [payload.get("format", {}).get("duration"), video.get("duration")]
    duration = 0.0
    for value in duration_values:
        try:
            candidate = float(value)
        except (TypeError, ValueError):
            continue
        if candidate > duration:
            duration = candidate
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rotation = 0
    for side_data in video.get("side_data_list") or []:
        if "rotation" in side_data:
            rotation = int(float(side_data.get("rotation") or 0))
    if abs(rotation) in {90, 270}:
        width, height = height, width
    return {
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")), 3),
        "rotation": rotation,
        "video_codec": video.get("codec_name"),
        "pixel_format": video.get("pix_fmt"),
        "color_range": video.get("color_range"),
        "has_audio": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": int(audio.get("sample_rate") or 0) if audio else 0,
        "channels": int(audio.get("channels") or 0) if audio else 0,
        "format_name": payload.get("format", {}).get("format_name"),
    }


def decode_media(path: Path, root: Path) -> Tuple[bool, str]:
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg is None:
        return False, "ffmpeg is not available"
    sink = "NUL" if os.name == "nt" else "/dev/null"
    result = run_command(
        [str(ffmpeg), "-nostdin", "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", sink],
        root=root,
        capture=True,
    )
    detail = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, detail


def validate_normalized_proxy(path: Path, root: Path, *, width: int, height: int, fps: float, source_duration: float) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    media = probe_media(path, root)
    if media["width"] != width or media["height"] != height:
        errors.append(f"dimensions are {media['width']}x{media['height']}, expected {width}x{height}")
    if abs(float(media["fps"]) - float(fps)) > 0.02:
        errors.append(f"fps is {media['fps']}, expected {fps:g}")
    if media.get("video_codec") != "h264":
        errors.append(f"video codec is {media.get('video_codec')}, expected h264")
    if media.get("pixel_format") != "yuv420p":
        errors.append(f"pixel format is {media.get('pixel_format')}, expected yuv420p")
    if media.get("color_range") != "tv":
        errors.append(f"color range is {media.get('color_range')}, expected tv")
    if media.get("audio_codec") != "aac":
        errors.append(f"audio codec is {media.get('audio_codec')}, expected aac")
    if media.get("sample_rate") != 48000:
        errors.append(f"audio sample rate is {media.get('sample_rate')}, expected 48000")
    if media.get("channels") != 2:
        errors.append(f"audio channels are {media.get('channels')}, expected 2")
    if abs(float(media["duration"]) - float(source_duration)) > 0.25:
        errors.append(f"duration drift is {float(media['duration']) - float(source_duration):.3f}s")
    decoded, detail = decode_media(path, root)
    if not decoded:
        errors.append(f"full decode failed: {detail or 'unknown ffmpeg error'}")
    return media, errors


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        common = os.path.commonpath([str(path.resolve()), str(directory.resolve())])
        return os.path.normcase(common) == os.path.normcase(str(directory.resolve()))
    except ValueError:
        return False


def is_reparse_path(path: Path) -> bool:
    try:
        is_junction = getattr(path, "is_junction", None)
        attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return path.is_symlink() or bool(callable(is_junction) and is_junction()) or bool(attributes & reparse_flag)
    except OSError:
        return True


def resolve_project_path(value: os.PathLike[str] | str) -> Path:
    lexical = Path(os.path.abspath(Path(value).expanduser()))
    cursor = lexical
    while True:
        if os.path.lexists(cursor) and is_reparse_path(cursor):
            raise RuntimeError(f"project path traverses a symlink or junction: {cursor}")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    resolved = lexical.resolve()
    if resolved.exists():
        assert_project_tree_no_reparse(resolved)
    return resolved


def assert_project_tree_no_reparse(project: Path) -> None:
    if not project.exists():
        return
    if not project.is_dir():
        raise RuntimeError(f"project path is not a directory: {project}")
    for current, directories, files in os.walk(project, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_directories: List[str] = []
        for name in directories:
            candidate = current_path / name
            if is_reparse_path(candidate):
                raise RuntimeError(f"project contains a symlink or junction: {candidate}")
            safe_directories.append(name)
        directories[:] = safe_directories
        for name in files:
            candidate = current_path / name
            if is_reparse_path(candidate):
                raise RuntimeError(f"project contains a linked file: {candidate}")


def canonical_payload_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def runtime_integrity_errors(root: Path, *, require_asr: bool = False) -> List[str]:
    errors: List[str] = []
    runtime_path = root / ".tools" / "travel-vlog-runtime.json"
    lock_path = skill_dir() / "assets" / "upstream-lock.json"
    try:
        runtime = load_json(runtime_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"runtime manifest is missing or unreadable: {exc}"]
    try:
        lock = load_json(lock_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"upstream lock is missing or unreadable: {exc}"]
    if runtime.get("schema_version") != "travel-vlog-runtime/2":
        errors.append("runtime manifest schema is missing or unsupported")
    if lock.get("schema_version") != "travel-vlog-upstream-lock/2":
        errors.append("upstream lock schema is missing or unsupported")
    if require_asr and runtime.get("asr_installed") is not True:
        errors.append("ASR dependencies are not installed in the approved runtime")

    runtime_python = Path(str(runtime.get("python") or "")).resolve()
    if runtime_python != Path(sys.executable).resolve():
        errors.append("pipeline is not running with the approved project-local Python")
    elif not runtime_python.is_file() or file_sha256(runtime_python).upper() != str(runtime.get("python_sha256") or "").upper():
        errors.append("approved Python executable changed after runtime setup")

    selected_ffmpeg, selected_ffprobe = find_ffmpeg_tools(root)
    for label, selected, manifest_key, manifest_hash_key in (
        ("FFmpeg", selected_ffmpeg, "ffmpeg", "ffmpeg_sha256"),
        ("FFprobe", selected_ffprobe, "ffprobe", "ffprobe_sha256"),
    ):
        approved = Path(str(runtime.get(manifest_key) or "")).resolve()
        if selected is None or selected.resolve() != approved:
            errors.append(f"selected {label} does not match the approved runtime")
        elif not approved.is_file() or file_sha256(approved).upper() != str(runtime.get(manifest_hash_key) or "").upper():
            errors.append(f"approved {label} executable changed after runtime setup")

    current_lock_hash = file_sha256(lock_path).upper() if lock_path.is_file() else ""
    if current_lock_hash != str(runtime.get("upstream_lock_sha256") or "").upper():
        errors.append("runtime manifest is bound to a different upstream lock")
    runtime_integrity_path = skill_dir() / "scripts" / "runtime_integrity.py"
    if (
        not runtime_integrity_path.is_file()
        or file_sha256(runtime_integrity_path).upper() != str(runtime.get("runtime_integrity_sha256") or "").upper()
    ):
        errors.append("runtime integrity verifier changed after runtime setup")
    launcher_path = skill_dir() / "scripts" / "run_pipeline.ps1"
    if not launcher_path.is_file() or file_sha256(launcher_path).upper() != str(runtime.get("pipeline_launcher_sha256") or "").upper():
        errors.append("secure pipeline launcher changed after runtime setup")
    asr_installed = runtime.get("asr_installed") is True
    expected_lock_name = "requirements-windows-py312.lock.txt" if asr_installed else "requirements-core.txt"
    package_lock = skill_dir() / "assets" / expected_lock_name
    if Path(str(runtime.get("package_lock") or "")).name.lower() != expected_lock_name.lower():
        errors.append("runtime manifest names the wrong Python requirements file")
    elif not package_lock.is_file() or file_sha256(package_lock).upper() != str(runtime.get("package_lock_sha256") or "").upper():
        errors.append("approved Python requirements file changed after runtime setup")
    distribution_record = installed_distribution_record()
    if (
        list(runtime.get("python_distributions") or []) != distribution_record["distributions"]
        or str(runtime.get("python_distributions_sha256") or "").lower() != distribution_record["sha256"]
    ):
        errors.append("installed Python distribution versions differ from the approved runtime")

    tree_records, tree_errors = verify_vendor_lock(root, lock_path)
    errors.extend(tree_errors)
    runtime_trees = {
        str(item.get("name")): (str(item.get("sha256") or "").lower(), int(item.get("file_count") or 0))
        for item in (runtime.get("upstream_trees") or [])
        if isinstance(item, Mapping)
    }
    current_trees = {
        str(item.get("name")): (str(item.get("sha256") or "").lower(), int(item.get("file_count") or 0))
        for item in tree_records
    }
    if runtime_trees != current_trees:
        errors.append("runtime vendor tree snapshot differs from current pinned vendor trees")
    return list(dict.fromkeys(errors))


def require_runtime_integrity(root: Path, *, require_asr: bool = False) -> None:
    errors = runtime_integrity_errors(root, require_asr=require_asr)
    if errors:
        raise RuntimeError("runtime integrity check failed: " + "; ".join(errors))


def frame_times(duration: float) -> List[float]:
    if duration <= 0:
        return []
    if duration <= 20:
        raw = [min(0.5, duration / 4), duration / 2, max(0.0, duration - min(0.5, duration / 4))]
    elif duration <= 60:
        raw = [duration * fraction for fraction in (0.08, 0.29, 0.5, 0.71, 0.92)]
    else:
        raw = [min(duration - 0.1, value) for value in range(0, int(duration) + 1, 15)]
        if len(raw) > 40:
            step = (len(raw) - 1) / 39
            raw = [raw[round(index * step)] for index in range(40)]
    return sorted({round(max(0.0, min(duration - 0.05, value)), 3) for value in raw})


def safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:80] or "video"


def next_versioned_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"_V\d+$", "", path.stem)
    versions = []
    pattern = re.compile(rf"^{re.escape(stem)}_V(\d+){re.escape(path.suffix)}$")
    for candidate in path.parent.iterdir():
        match = pattern.match(candidate.name)
        if match:
            versions.append(int(match.group(1)))
    return path.parent / f"{stem}_V{max(versions, default=0) + 1}{path.suffix}"


@contextlib.contextmanager
def exclusive_render_lock(project: Path) -> Iterable[None]:
    lock_path = project / "work" / ".render.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"another render appears to be active; inspect stale lock: {lock_path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} nonce={uuid.uuid4().hex}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def cmd_doctor(args: argparse.Namespace) -> int:
    root = find_workspace_root()
    checks: List[Dict[str, Any]] = []
    python_ok = sys.version_info >= (3, 12)
    checks.append({"name": "python", "status": "ok" if python_ok else "missing", "detail": sys.version.split()[0], "path": sys.executable})
    ffmpeg, ffprobe = find_ffmpeg_tools(root)
    checks.append({"name": "ffmpeg", "status": "ok" if ffmpeg else "missing", "path": str(ffmpeg) if ffmpeg else None})
    checks.append({"name": "ffprobe", "status": "ok" if ffprobe else "missing", "path": str(ffprobe) if ffprobe else None})
    cjk_font = find_cjk_font()
    checks.append({"name": "CJK font", "status": "ok" if cjk_font else "missing", "path": str(cjk_font) if cjk_font else None})

    if root:
        maxazure, vlog = vendor_paths(root)
        lock_path = skill_dir() / "assets" / "upstream-lock.json"
        lock = load_json(lock_path) if lock_path.is_file() else {"sources": []}
        lock_by_name = {item.get("name"): item for item in lock.get("sources") or []}
        lock_schema_ok = lock.get("schema_version") == "travel-vlog-upstream-lock/2"
        checks.append({"name": "upstream lock schema", "status": "ok" if lock_schema_ok else "changed", "path": str(lock_path)})
        for name, directory in (("maxazure-video-editing-skill", maxazure), ("vlog-auto-edit", vlog)):
            skill_path = directory / "SKILL.md"
            source_lock = lock_by_name.get(name) or {}
            expected = source_lock.get("skill_sha256")
            actual = file_sha256(skill_path).upper() if skill_path.is_file() else None
            status = "ok" if actual and (not expected or actual == str(expected).upper()) else ("changed" if actual else "missing")
            checks.append({"name": name, "status": status, "path": str(directory), "expected_sha256": expected, "actual_sha256": actual})
            for relative, script_expected in (source_lock.get("script_sha256") or {}).items():
                normalized_relative = str(relative).replace("\\", "/")
                script_path = (directory / str(relative)).resolve()
                script_actual = file_sha256(script_path).upper() if script_path.is_file() else None
                script_status = "ok" if script_actual == str(script_expected).upper() else ("changed" if script_actual else "missing")
                checks.append({
                    "name": f"{name}:{normalized_relative}",
                    "status": script_status,
                    "path": str(script_path),
                    "expected_sha256": script_expected,
                    "actual_sha256": script_actual,
                })

        runtime_path = root / ".tools" / "travel-vlog-runtime.json"
        try:
            runtime = load_json(runtime_path)
        except (OSError, json.JSONDecodeError):
            runtime = {}
        runtime_ok = runtime.get("schema_version") == "travel-vlog-runtime/2"
        checks.append({"name": "runtime manifest", "status": "ok" if runtime_ok else ("changed" if runtime_path.is_file() else "missing"), "path": str(runtime_path)})
        if runtime:
            runtime_files = (
                ("runtime python", Path(str(runtime.get("python") or "")), runtime.get("python_sha256")),
                ("runtime ffmpeg", Path(str(runtime.get("ffmpeg") or "")), runtime.get("ffmpeg_sha256")),
                ("runtime ffprobe", Path(str(runtime.get("ffprobe") or "")), runtime.get("ffprobe_sha256")),
            )
            for label, path, expected_hash in runtime_files:
                actual_hash = file_sha256(path).upper() if path.is_file() else None
                file_status = "ok" if actual_hash and actual_hash == str(expected_hash or "").upper() else ("changed" if actual_hash else "missing")
                checks.append({"name": label, "status": file_status, "path": str(path), "expected_sha256": expected_hash, "actual_sha256": actual_hash})
            selected_pair_matches = (
                ffmpeg is not None
                and ffprobe is not None
                and ffmpeg.resolve() == Path(str(runtime.get("ffmpeg") or "")).resolve()
                and ffprobe.resolve() == Path(str(runtime.get("ffprobe") or "")).resolve()
            )
            checks.append({
                "name": "selected FFmpeg pair binding",
                "status": "ok" if selected_pair_matches else "changed",
                "detail": "selected tools must equal runtime manifest paths",
            })
            current_lock_hash = file_sha256(lock_path).upper() if lock_path.is_file() else None
            checks.append({
                "name": "runtime upstream lock binding",
                "status": "ok" if current_lock_hash and current_lock_hash == str(runtime.get("upstream_lock_sha256") or "").upper() else "changed",
                "path": str(lock_path),
            })
            expected_package_name = "requirements-windows-py312.lock.txt" if runtime.get("asr_installed") is True else "requirements-core.txt"
            package_lock = skill_dir() / "assets" / expected_package_name
            current_package_hash = file_sha256(package_lock).upper() if package_lock.is_file() else None
            manifest_package_name = Path(str(runtime.get("package_lock") or "")).name.lower()
            checks.append({
                "name": "runtime package lock binding",
                "status": "ok" if current_package_hash and manifest_package_name == expected_package_name.lower() and current_package_hash == str(runtime.get("package_lock_sha256") or "").upper() else "changed",
                "path": str(package_lock),
            })
            runtime_integrity_path = skill_dir() / "scripts" / "runtime_integrity.py"
            runtime_integrity_hash = file_sha256(runtime_integrity_path).upper() if runtime_integrity_path.is_file() else None
            checks.append({
                "name": "runtime integrity verifier binding",
                "status": "ok" if runtime_integrity_hash and runtime_integrity_hash == str(runtime.get("runtime_integrity_sha256") or "").upper() else "changed",
                "path": str(runtime_integrity_path),
            })
            launcher_path = skill_dir() / "scripts" / "run_pipeline.ps1"
            launcher_hash = file_sha256(launcher_path).upper() if launcher_path.is_file() else None
            checks.append({
                "name": "secure pipeline launcher binding",
                "status": "ok" if launcher_hash and launcher_hash == str(runtime.get("pipeline_launcher_sha256") or "").upper() else "changed",
                "path": str(launcher_path),
            })
            distribution_record = installed_distribution_record()
            distributions_match = (
                list(runtime.get("python_distributions") or []) == distribution_record["distributions"]
                and str(runtime.get("python_distributions_sha256") or "").lower() == distribution_record["sha256"]
            )
            checks.append({
                "name": "runtime Python distribution binding",
                "status": "ok" if distributions_match else "changed",
                "detail": f"{len(distribution_record['distributions'])} distributions",
            })
            expected_script_snapshots = {
                (str(item.get("source")), str(item.get("relative_path"))): str(item.get("sha256") or "").upper()
                for item in (runtime.get("upstream_scripts") or [])
                if isinstance(item, Mapping)
            }
            lock_script_snapshots = {
                (str(source.get("name")), str(relative).replace("\\", "/")): str(digest).upper()
                for source in (lock.get("sources") or [])
                for relative, digest in (source.get("script_sha256") or {}).items()
            }
            checks.append({
                "name": "runtime upstream script binding",
                "status": "ok" if expected_script_snapshots == lock_script_snapshots else "changed",
                "detail": f"{len(expected_script_snapshots)} scripts",
            })
            tree_records, tree_errors = verify_vendor_lock(root, lock_path)
            runtime_trees = {
                str(item.get("name")): (str(item.get("sha256") or "").lower(), int(item.get("file_count") or 0))
                for item in (runtime.get("upstream_trees") or [])
                if isinstance(item, Mapping)
            }
            current_trees = {
                str(item.get("name")): (str(item.get("sha256") or "").lower(), int(item.get("file_count") or 0))
                for item in tree_records
            }
            checks.append({
                "name": "runtime vendor tree binding",
                "status": "ok" if not tree_errors and runtime_trees == current_trees else "changed",
                "detail": "; ".join(tree_errors) if tree_errors else f"{len(current_trees)} trees",
            })
    else:
        checks.append({"name": "workspace", "status": "missing", "detail": "workspace root with pinned vendor sources was not found"})

    for module, label, required in (("PIL", "Pillow", True), ("yaml", "PyYAML", True), ("faster_whisper", "faster-whisper", bool(args.require_asr))):
        try:
            __import__(module)
            status = "ok"
        except ImportError:
            status = "missing" if required else "optional_missing"
        checks.append({"name": label, "status": status})

    blocking = [check for check in checks if check["status"] in {"missing", "changed"}]
    report = {
        "schema_version": "travel-vlog-doctor/1",
        "generated_at": utc_now(),
        "status": "ready" if not blocking else "blocked",
        "workspace": str(root) if root else None,
        "checks": checks,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            print(f"[{check['status']}] {check['name']}: {check.get('path') or check.get('detail') or ''}")
        print(f"status={report['status']}")
    return 0 if not blocking else 2


def inventory_to_analysis(inventory: Mapping[str, Any], *, profile: str, target_duration: float, title: str, root: Path) -> Dict[str, Any]:
    clips: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for index, item in enumerate(inventory.get("files") or []):
        if item.get("media_type") != "video":
            continue
        path = Path(str(item.get("project_path") or "")).resolve()
        if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
            continue
        try:
            media = probe_media(path, root)
        except (RuntimeError, json.JSONDecodeError) as exc:
            warnings.append(f"probe failed for {path}: {exc}")
            continue
        clips.append({
            "file": str(path),
            "filename": path.name,
            "duration": media["duration"],
            "width": media["width"],
            "height": media["height"],
            "fps": media["fps"],
            "resolution": f"{media['width']}x{media['height']}",
            "source_sha256": item.get("sha256"),
            "source_index": index,
            "category": item.get("category"),
            "visual": [],
            "review_frame_times": frame_times(media["duration"]),
            "audio": {
                "has_track": media["has_audio"],
                "has_speech": False,
                "mean_volume_db": None,
                "max_volume_db": None,
                "transcript": [],
            },
            "preprocessing": {
                "mode": "normal",
                "original_range": [0.0, media["duration"]],
                "recommended_range": [0.0, media["duration"]],
                "skip_zones": [],
            },
            "labels": {
                "story_role": "unclassified",
                "content_class": "unclassified",
                "quality": None,
                "keep": True,
                "human_override": False,
            },
        })
    return {
        "schema_version": ANALYSIS_VERSION,
        "generated_at": utc_now(),
        "status": "needs_visual_review" if clips else "blocked",
        "project": {
            "title": title,
            "profile": profile,
            "target_duration_s": target_duration,
            "project_dir": inventory.get("project_dir"),
        },
        "clips": clips,
        "warnings": warnings,
    }


def cmd_prepare(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    project = resolve_project_path(args.project)
    inventory_path = project / "work" / "source_inventory.json"
    if inventory_path.is_file() and not args.reimport:
        inventory = load_json(inventory_path)
        missing = [item.get("project_path") for item in inventory.get("files") or [] if item.get("project_path") and not Path(item["project_path"]).is_file()]
        if missing:
            raise RuntimeError("existing inventory references missing files; use a new project or --reimport after review")
        changed: List[str] = []
        for item in inventory.get("files") or []:
            project_path = Path(str(item.get("project_path") or ""))
            expected = str(item.get("sha256") or "").lower()
            if not project_path.is_file() or not expected:
                changed.append(str(project_path or item.get("filename") or "unknown"))
                continue
            if file_sha256(project_path).lower() != expected:
                changed.append(str(project_path))
        if changed:
            raise RuntimeError(
                "existing inventory content changed after import; use --reimport and --rebuild-analysis after review: "
                + ", ".join(changed[:5])
            )
        print(f"Reusing existing inventory: {inventory_path}")
    else:
        command_args: List[str] = []
        for source in args.source:
            command_args += ["--source", str(Path(source).expanduser().resolve())]
        command_args += [
            "--project-dir", str(project),
            "--title", args.title,
            "--mode", args.mode,
            "--hash",
            "--strict",
        ]
        result = run_upstream(root, "maxazure", "project_bootstrap.py", command_args, cwd=root)
        if result.returncode != 0:
            return result.returncode
        inventory = load_json(inventory_path)

    analysis_path = project / "work" / "clip_analysis.json"
    if analysis_path.exists() and not args.rebuild_analysis:
        print(f"Preserving existing analysis: {analysis_path}")
    else:
        analysis = inventory_to_analysis(
            inventory,
            profile=args.profile,
            target_duration=args.target_duration,
            title=args.title,
            root=root,
        )
        if analysis_path.exists():
            backup_json(analysis_path, "prepare")
        write_json(analysis_path, analysis)
    manifest = {
        "schema_version": "travel-vlog-frame-review/1",
        "generated_at": utc_now(),
        "analysis": str(analysis_path),
        "clips": [
            {"file": clip["file"], "times": clip.get("review_frame_times") or frame_times(float(clip.get("duration") or 0))}
            for clip in normalize_analysis(load_json(analysis_path))["clips"]
        ],
    }
    write_json(project / "work" / "frame_review_manifest.json", manifest)
    print(json.dumps({"project": str(project), "inventory": str(inventory_path), "analysis": str(analysis_path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_frames(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for frame extraction")
    analysis_path = Path(args.analysis).expanduser().resolve()
    analysis = normalize_analysis(load_json(analysis_path), base_dir=analysis_path.parent)
    out = Path(args.out).expanduser().resolve()
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    clips = analysis["clips"][: args.max_clips if args.max_clips else None]
    for clip_index, clip in enumerate(clips, start=1):
        source = Path(clip["file"])
        clip_dir = out / f"{clip_index:04d}-{safe_stem(source.stem)}"
        clip_dir.mkdir(parents=True, exist_ok=True)
        times = clip.get("review_frame_times") or frame_times(float(clip.get("duration") or 0))
        frame_entries: List[Dict[str, Any]] = []
        for at in times:
            output = clip_dir / f"t{int(round(float(at) * 1000)):09d}.jpg"
            if not output.is_file() or args.force:
                result = run_command(
                    [
                        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", f"{float(at):.3f}", "-i", str(source),
                        "-frames:v", "1", "-vf", "scale=1280:-2:force_original_aspect_ratio=decrease",
                        "-q:v", "2", str(output),
                    ],
                    root=root,
                    capture=True,
                )
                if result.returncode != 0:
                    errors.append(f"{source}@{at}: {(result.stderr or '').strip()}")
                    continue
            frame_entries.append({"time": float(at), "image": str(output)})
        items.append({"file": str(source), "frames": frame_entries})
    manifest = {
        "schema_version": "travel-vlog-review-frames/1",
        "generated_at": utc_now(),
        "status": "ready" if not errors else "warn",
        "analysis": str(analysis_path),
        "items": items,
        "errors": errors,
    }
    write_json(out / "frame_manifest.json", manifest)
    print(json.dumps({"manifest": str(out / 'frame_manifest.json'), "clips": len(items), "errors": len(errors)}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def cmd_transcribe(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root, require_asr=True)
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for transcription preparation")
    analysis_path = Path(args.analysis).expanduser().resolve()
    analysis = normalize_analysis(load_json(analysis_path), base_dir=analysis_path.parent)
    project = resolve_project_path(args.project)
    audio_dir = project / "work" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    selected: List[Dict[str, Any]] = []
    for clip in analysis["clips"]:
        audio = clip.get("audio") or {}
        labels = clip.get("labels") or {}
        if not audio.get("has_track"):
            continue
        if args.all or audio.get("has_speech") or labels.get("needs_transcript"):
            selected.append(clip)
    if args.limit:
        selected = selected[: args.limit]
    if not selected:
        print("No clips selected for ASR. Mark labels.needs_transcript=true or rerun with --all.")
        return 0

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed; run setup_runtime.ps1 -WithAsr") from exc
    os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")
    model_dir = project / "work" / "models" / "faster-whisper"
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
            download_root=str(model_dir),
        )
    except Exception as exc:
        raise RuntimeError(
            f"could not load faster-whisper on device={args.device}, compute_type={args.compute_type}: {exc}"
        ) from exc

    errors: List[str] = []
    for index, clip in enumerate(selected, start=1):
        source = Path(clip["file"])
        wav = audio_dir / f"{index:04d}-{safe_stem(source.stem)}_audio.wav"
        extract = run_command(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
            ],
            root=root,
            capture=True,
        )
        if extract.returncode != 0:
            errors.append(f"audio extraction failed for {source}: {(extract.stderr or '').strip()}")
            continue
        try:
            options: Dict[str, Any] = {"word_timestamps": args.word_timestamps}
            if args.language:
                options["language"] = args.language
            segments_iter, info = model.transcribe(str(wav), **options)
            segments: List[Dict[str, Any]] = []
            for segment_id, segment in enumerate(segments_iter, start=1):
                entry: Dict[str, Any] = {
                    "id": segment_id,
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": str(segment.text or "").strip(),
                }
                if args.word_timestamps and segment.words:
                    entry["words"] = [
                        {"word": str(word.word or "").strip(), "start": round(float(word.start), 3), "end": round(float(word.end), 3)}
                        for word in segment.words
                        if str(word.word or "").strip()
                    ]
                segments.append(entry)
            transcript_path = wav.with_name(wav.stem.replace("_audio", "") + "_transcript.json")
            payload = {
                "source_audio": str(wav),
                "engine": "faster-whisper",
                "model": args.model,
                "device": args.device,
                "compute_type": args.compute_type,
                "language": getattr(info, "language", args.language or "unknown"),
                "segments": segments,
            }
            write_json(transcript_path, payload)
        except Exception as exc:
            errors.append(f"transcription failed for {source}: {exc}")
            continue
        clip["audio"]["has_speech"] = bool(payload.get("segments"))
        clip["audio"]["transcript"] = payload.get("segments") or []
        clip["audio"]["transcript_path"] = str(transcript_path)
    backup_json(analysis_path, "pre-asr")
    analysis["asr_at"] = utc_now()
    analysis["asr_errors"] = errors
    write_json(analysis_path, analysis)
    print(json.dumps({"analysis": str(analysis_path), "selected": len(selected), "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def cmd_classify(args: argparse.Namespace) -> int:
    analysis_path = Path(args.analysis).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else analysis_path
    classified = classify_analysis(load_json(analysis_path), profile=args.profile, force=args.force, base_dir=analysis_path.parent)
    if output == analysis_path:
        backup_json(analysis_path, "pre-classify")
    write_json(output, classified)
    counts: Dict[str, int] = {}
    for clip in classified["clips"]:
        role = str(clip.get("labels", {}).get("story_role") or "other")
        counts[role] = counts.get(role, 0) + 1
    print(json.dumps({"output": str(output), "roles": counts}, ensure_ascii=False, indent=2))
    return 0


def profile_path(name: str) -> Path:
    filename = "food-profile.json" if name == "food" else "travel-profile.json"
    return skill_dir() / "assets" / filename


def cmd_plan(args: argparse.Namespace) -> int:
    analysis_path = Path(args.analysis).expanduser().resolve()
    profile = load_profile(profile_path(args.profile))
    analysis = load_json(analysis_path)
    plan = build_story_plan(
        analysis,
        profile=profile,
        title=args.title,
        target_duration_s=args.target_duration,
        base_dir=analysis_path.parent,
    )
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        backup_json(output, "pre-plan")
    write_json(output, plan)
    print(json.dumps({"output": str(output), "summary": plan["summary"], "coverage": plan["coverage"], "warnings": plan["warnings"]}, ensure_ascii=False, indent=2))
    return 0 if plan["summary"]["selected_clips"] else 2


def cmd_review(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    analysis_path = Path(args.analysis).expanduser().resolve()
    plan_path = Path(args.plan).expanduser().resolve()
    footage = Path(args.footage).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    normalized = normalize_analysis(load_json(analysis_path), base_dir=analysis_path.parent)
    compat: List[Dict[str, Any]] = []
    for clip in normalized["clips"]:
        item = copy.deepcopy(clip)
        item["filename"] = clip["file"]
        item["resolution"] = f"{clip.get('width', 0)}x{clip.get('height', 0)}"
        compat.append(item)
    compat_path = out / "clip_analysis_compat.json"
    write_json(compat_path, compat)
    dashboard = run_upstream(
        root,
        "vlog",
        "gen_dashboard.py",
        [
            "--analysis", str(compat_path), "--plan", str(plan_path),
            "--footage", str(footage), "--out", str(out), "--skip-qc",
        ],
        cwd=root,
    )
    storyboard_dir = out / "storyboard"
    storyboard = run_upstream(
        root,
        "vlog",
        "gen_storyboard.py",
        ["--plan", str(plan_path), "--footage", str(footage), "--out", str(storyboard_dir)],
        cwd=root,
    )
    result = {
        "dashboard": str(out / "dashboard.html"),
        "storyboard": str(storyboard_dir / "index.html"),
        "dashboard_exit": dashboard.returncode,
        "storyboard_exit": storyboard.returncode,
    }
    if dashboard.returncode == 0 and storyboard.returncode == 0:
        dashboard_path = out / "dashboard.html"
        storyboard_path = storyboard_dir / "index.html"
        if not dashboard_path.is_file() or not storyboard_path.is_file():
            result["error"] = "review generators returned success without both HTML outputs"
        else:
            manifest = {
                "schema_version": "travel-vlog-story-review/1",
                "generated_at": utc_now(),
                "status": "ready",
                "analysis": {"path": str(analysis_path), "sha256": file_sha256(analysis_path)},
                "plan": {"path": str(plan_path), "sha256": file_sha256(plan_path)},
                "compat_analysis": {"path": str(compat_path), "sha256": file_sha256(compat_path)},
                "dashboard": {"path": str(dashboard_path), "sha256": file_sha256(dashboard_path)},
                "storyboard": {"path": str(storyboard_path), "sha256": file_sha256(storyboard_path)},
                "review_tree": directory_tree_record(out),
                "selected_clip_ids": [
                    str(clip.get("candidate_id") or "")
                    for clip in selected_plan_clips(load_json(plan_path))
                ],
            }
            manifest_path = plan_path.parent / "story_review_manifest.json"
            write_json(manifest_path, manifest)
            result["review_manifest"] = str(manifest_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if dashboard.returncode == 0 and storyboard.returncode == 0 and not result.get("error") else 2


def resolve_plan_source(raw: str, project: Path, plan_dir: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidates = [plan_dir / path, project / "origin" / "raw" / path, project / path]
    existing = [candidate.resolve() for candidate in candidates if candidate.is_file()]
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1 and len({str(item) for item in existing}) == 1:
        return existing[0]
    raise RuntimeError(f"cannot resolve plan source: {raw}")


def proxy_filter(width: int, height: int, fps: float, fit: str) -> str:
    if fit == "crop":
        size = f"scale={width}:{height}:force_original_aspect_ratio=increase:out_range=tv,crop={width}:{height}"
    else:
        size = f"scale={width}:{height}:force_original_aspect_ratio=decrease:out_range=tv,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    return f"{size},format=yuv420p,setsar=1,fps={fps:g}"


def cmd_normalize(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for proxy normalization")
    project = resolve_project_path(args.project)
    plan_path = Path(args.plan).expanduser().resolve()
    plan = load_json(plan_path)
    sources: List[Path] = []
    for section in plan.get("structure") or []:
        for clip in section.get("clips") or []:
            source = resolve_plan_source(str(clip.get("file") or ""), project, plan_path.parent)
            if source not in sources:
                sources.append(source)
    proxy_dir = project / "work" / "proxies"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    map_path = project / "work" / "proxy_map.json"
    existing = load_json(map_path) if map_path.is_file() else {"items": []}
    existing_by_source = {os.path.normcase(str(Path(item.get("source", "")).resolve())): item for item in existing.get("items") or [] if item.get("source")}
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    for source in sources:
        source_hash = file_sha256(source)
        fingerprint_input = f"{source.resolve()}|{source_hash}|{args.width}|{args.height}|{args.fps}|{args.fit}|yuv420p-tv-v2"
        fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()
        output = proxy_dir / f"{safe_stem(source.stem)}-{fingerprint[:10]}.mp4"
        prior = existing_by_source.get(os.path.normcase(str(source.resolve())))
        if prior and prior.get("fingerprint") == fingerprint and not args.force:
            prior_proxy = Path(str(prior.get("proxy") or ""))
            expected_proxy_hash = str(prior.get("proxy_sha256") or "").lower()
            if (
                str(prior.get("source_sha256") or "").lower() == source_hash.lower()
                and prior_proxy.is_file()
                and expected_proxy_hash
                and file_sha256(prior_proxy).lower() == expected_proxy_hash
            ):
                try:
                    source_media = probe_media(source, root)
                    proxy_media, proxy_errors = validate_normalized_proxy(
                        prior_proxy,
                        root,
                        width=args.width,
                        height=args.height,
                        fps=args.fps,
                        source_duration=source_media["duration"],
                    )
                    if not proxy_errors:
                        reused = copy.deepcopy(prior)
                        reused.update({
                            "status": "reused",
                            "source_sha256": source_hash,
                            "proxy_sha256": expected_proxy_hash,
                            "source_media": source_media,
                            "proxy_media": proxy_media,
                        })
                        items.append(reused)
                        continue
                except (RuntimeError, OSError, json.JSONDecodeError):
                    pass
        try:
            media = probe_media(source, root)
            if media["duration"] <= 0:
                raise RuntimeError("source duration is zero")
            command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source)]
            if media["has_audio"]:
                command += ["-map", "0:v:0", "-map", "0:a:0"]
            else:
                command += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-map", "0:v:0", "-map", "1:a:0"]
            command += [
                "-vf", proxy_filter(args.width, args.height, args.fps, args.fit),
                "-fps_mode", "cfr", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-x264-params", "bframes=0", "-pix_fmt", "yuv420p", "-color_range", "tv",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                "-af", "aresample=async=1:first_pts=0", "-t", f"{media['duration']:.6f}",
                "-movflags", "+faststart", str(output),
            ]
            result = run_command(command, root=root, capture=True)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "ffmpeg failed").strip())
            verified, proxy_errors = validate_normalized_proxy(
                output,
                root,
                width=args.width,
                height=args.height,
                fps=args.fps,
                source_duration=media["duration"],
            )
            if proxy_errors:
                raise RuntimeError("; ".join(proxy_errors))
            proxy_hash = file_sha256(output)
            items.append({
                "source": str(source.resolve()),
                "proxy": str(output.resolve()),
                "fingerprint": fingerprint,
                "status": "ready",
                "source_sha256": source_hash,
                "proxy_sha256": proxy_hash,
                "source_media": media,
                "proxy_media": verified,
                "target": {
                    "width": args.width,
                    "height": args.height,
                    "fps": args.fps,
                    "fit": args.fit,
                    "pixel_format": "yuv420p",
                    "color_range": "tv",
                },
            })
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{source}: {exc}")
            items.append({
                "source": str(source),
                "proxy": str(output),
                "fingerprint": fingerprint,
                "status": "blocked",
                "source_sha256": source_hash,
                "error": str(exc),
            })
    payload = {
        "schema_version": "travel-vlog-proxy-map/1",
        "generated_at": utc_now(),
        "status": "ready" if not errors else "blocked",
        "items": items,
        "errors": errors,
    }
    if map_path.exists():
        backup_json(map_path, "pre-normalize")
    write_json(map_path, payload)
    print(json.dumps({"proxy_map": str(map_path), "sources": len(sources), "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


def cmd_compile(args: argparse.Namespace) -> int:
    project = resolve_project_path(args.project)
    analysis_path = Path(args.analysis).expanduser().resolve()
    plan_path = Path(args.plan).expanduser().resolve()
    proxy_path = Path(args.proxy_map).expanduser().resolve() if args.proxy_map else project / "work" / "proxy_map.json"
    proxy_data = load_json(proxy_path) if proxy_path.is_file() else None
    compiled = compile_story(
        load_json(analysis_path),
        load_json(plan_path),
        project_dir=project,
        proxy_map_data=proxy_data,
        bgm=args.bgm,
        base_dir=analysis_path.parent,
    )
    plan_hash = story_plan_sha256(plan_path)
    compiled["timeline"]["source_plan_sha256"] = plan_hash
    compiled["report"]["source_plan"] = str(plan_path)
    compiled["report"]["source_plan_sha256"] = plan_hash
    compiled["report"]["artifact_payload_sha256"] = {
        "compiled_transcript.json": canonical_payload_sha256(compiled["transcript"]),
        "vlog_timeline.json": canonical_payload_sha256(compiled["timeline"]),
        "render_config.json": canonical_payload_sha256(compiled["render_config"]),
    }
    canonical_plan_path = project / "work" / "story_plan.json"
    paths = {
        "transcript": project / "work" / "compiled_transcript.json",
        "timeline": project / "work" / "vlog_timeline.json",
        "render_config": project / "work" / "render_config.json",
        "report": project / "work" / "compile_report.json",
    }
    if compiled["report"]["errors"]:
        report_path = paths["report"]
        compiled["report"]["published"] = False
        if report_path.exists():
            backup_json(report_path, "blocked-compile")
        write_json(report_path, compiled["report"])
        print(json.dumps({
            "report": str(report_path),
            "status": compiled["report"]["status"],
            "published": False,
            "errors": compiled["report"]["errors"],
        }, ensure_ascii=False, indent=2))
        return 2

    compiled["report"]["published"] = True
    if plan_path != canonical_plan_path:
        if canonical_plan_path.exists():
            backup_json(canonical_plan_path, "pre-compile")
        write_json(canonical_plan_path, load_json(plan_path))
    for key, path in paths.items():
        if path.exists():
            backup_json(path, "pre-compile")
        write_json(path, compiled[key])
    print(json.dumps({key: str(path) for key, path in paths.items()} | {"status": compiled["report"]["status"], "errors": compiled["report"]["errors"]}, ensure_ascii=False, indent=2))
    return 0


def selected_plan_clips(plan: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [
        clip
        for section in (plan.get("structure") or [])
        if isinstance(section, Mapping)
        for clip in (section.get("clips") or [])
        if isinstance(clip, Mapping)
    ]


def build_integrity_bundle(project: Path, *, require_preview: bool) -> Tuple[Dict[str, Any], List[str]]:
    """Hash the exact reviewed inputs, compiled artifacts, and render media."""
    project = project.resolve()
    assert_project_tree_no_reparse(project)
    work = project / "work"
    errors: List[str] = []
    hash_cache: Dict[str, str] = {}

    def hash_path(path: Path) -> Optional[str]:
        resolved = str(path.resolve())
        if resolved in hash_cache:
            return hash_cache[resolved]
        if not path.is_file():
            errors.append(f"integrity file is missing: {path}")
            return None
        try:
            value = file_sha256(path)
        except OSError as exc:
            errors.append(f"integrity file is unreadable: {path}: {exc}")
            return None
        hash_cache[resolved] = value
        return value

    artifacts: Dict[str, Dict[str, Any]] = {}
    artifact_paths = {
        "source_inventory": work / "source_inventory.json",
        "clip_analysis": work / "clip_analysis.json",
        "story_review_manifest": work / "story_review_manifest.json",
        "story_plan": work / "story_plan.json",
        "proxy_map": work / "proxy_map.json",
        "compiled_transcript": work / "compiled_transcript.json",
        "vlog_timeline": work / "vlog_timeline.json",
        "render_config": work / "render_config.json",
        "compile_report": work / "compile_report.json",
    }
    root = find_workspace_root()
    vendor_tree_records: List[Dict[str, Any]] = []
    if root is None:
        errors.append("workspace root is unavailable for integrity verification")
    else:
        errors.extend(runtime_integrity_errors(root))
        vendor_tree_records, vendor_tree_errors = verify_vendor_lock(root, skill_dir() / "assets" / "upstream-lock.json")
        errors.extend(vendor_tree_errors)
        artifact_paths.update({
            "runtime_manifest": root / ".tools" / "travel-vlog-runtime.json",
            "upstream_lock": skill_dir() / "assets" / "upstream-lock.json",
            "food_profile": skill_dir() / "assets" / "food-profile.json",
            "travel_profile": skill_dir() / "assets" / "travel-profile.json",
            "pipeline_code": skill_dir() / "scripts" / "pipeline.py",
            "core_code": skill_dir() / "scripts" / "vlog_core.py",
            "render_bridge_code": skill_dir() / "scripts" / "render_bridge.py",
            "runtime_integrity_code": skill_dir() / "scripts" / "runtime_integrity.py",
            "pipeline_launcher": skill_dir() / "scripts" / "run_pipeline.ps1",
        })
    for label, path in artifact_paths.items():
        digest = hash_path(path)
        if digest:
            artifacts[label] = {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}

    payloads: Dict[str, Any] = {}
    for label, path in artifact_paths.items():
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            payloads[label] = load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label} is unreadable: {exc}")

    plan = payloads.get("story_plan") or {}
    analysis_data = payloads.get("clip_analysis") or {}
    story_review = payloads.get("story_review_manifest") or {}
    inventory = payloads.get("source_inventory") or {}
    proxy_data = payloads.get("proxy_map") or {}
    render_config = payloads.get("render_config") or {}
    transcript = payloads.get("compiled_transcript") or {}
    timeline = payloads.get("vlog_timeline") or {}
    compile_report = payloads.get("compile_report") or {}
    runtime = payloads.get("runtime_manifest") or {}
    upstream_lock = payloads.get("upstream_lock") or {}
    plan_path = artifact_paths["story_plan"]
    current_plan_hash = hash_path(plan_path)

    if story_review.get("schema_version") != "travel-vlog-story-review/1" or story_review.get("status") != "ready":
        errors.append("story review manifest is missing or not ready")
    if current_plan_hash and (story_review.get("plan") or {}).get("sha256") != current_plan_hash:
        errors.append("story review manifest does not match the current story plan")
    analysis_hash = artifacts.get("clip_analysis", {}).get("sha256")
    if analysis_hash and (story_review.get("analysis") or {}).get("sha256") != analysis_hash:
        errors.append("story review manifest does not match the current clip analysis")
    current_selected_ids = [str(clip.get("candidate_id") or "") for clip in selected_plan_clips(plan)]
    if list(story_review.get("selected_clip_ids") or []) != current_selected_ids:
        errors.append("story review manifest selected clips do not match the current story plan")
    for label in ("dashboard", "storyboard"):
        entry = story_review.get(label) or {}
        review_path = Path(str(entry.get("path") or "")).resolve()
        if not path_is_within(review_path, project / "verify"):
            errors.append(f"story review {label} is outside the project verify directory")
        review_hash = hash_path(review_path)
        if review_hash and review_hash != str(entry.get("sha256") or ""):
            errors.append(f"story review {label} changed after generation")
    review_tree = story_review.get("review_tree") or {}
    review_root = Path(str(review_tree.get("root") or "")).resolve()
    if not path_is_within(review_root, project / "verify"):
        errors.append("story review tree is outside the project verify directory")
    else:
        try:
            current_review_tree = directory_tree_record(review_root)
            if (
                current_review_tree.get("sha256") != review_tree.get("sha256")
                or current_review_tree.get("file_count") != review_tree.get("file_count")
            ):
                errors.append("story review thumbnails or frames changed after generation")
        except OSError as exc:
            errors.append(f"story review tree is unreadable: {exc}")

    if runtime.get("schema_version") != "travel-vlog-runtime/2":
        errors.append("runtime manifest schema is missing or unsupported")
    for label, key, hash_key in (
        ("runtime Python", "python", "python_sha256"),
        ("runtime FFmpeg", "ffmpeg", "ffmpeg_sha256"),
        ("runtime FFprobe", "ffprobe", "ffprobe_sha256"),
    ):
        runtime_file = Path(str(runtime.get(key) or ""))
        actual = hash_path(runtime_file)
        if not runtime.get(hash_key) or (actual and actual.lower() != str(runtime.get(hash_key)).lower()):
            errors.append(f"{label} differs from the runtime manifest")
    runtime_python = Path(str(runtime.get("python") or "")).resolve()
    if runtime_python != Path(sys.executable).resolve():
        errors.append("pipeline is not running with the project-local approved Python runtime")
    selected_ffmpeg, selected_ffprobe = find_ffmpeg_tools(root) if root else (None, None)
    if selected_ffmpeg is None or selected_ffmpeg != Path(str(runtime.get("ffmpeg") or "")).resolve():
        errors.append("selected FFmpeg does not match the runtime manifest")
    if selected_ffprobe is None or selected_ffprobe != Path(str(runtime.get("ffprobe") or "")).resolve():
        errors.append("selected FFprobe does not match the runtime manifest")
    if upstream_lock.get("schema_version") != "travel-vlog-upstream-lock/2":
        errors.append("upstream lock schema is missing or unsupported")
    if artifacts.get("upstream_lock", {}).get("sha256", "").lower() != str(runtime.get("upstream_lock_sha256") or "").lower():
        errors.append("runtime manifest is bound to a different upstream lock")
    package_lock_name = "requirements-windows-py312.lock.txt" if runtime.get("asr_installed") is True else "requirements-core.txt"
    package_lock = skill_dir() / "assets" / package_lock_name
    package_hash = hash_path(package_lock)
    if Path(str(runtime.get("package_lock") or "")).name.lower() != package_lock_name.lower():
        errors.append("runtime manifest names the wrong Python package lock")
    elif package_hash and package_hash.lower() != str(runtime.get("package_lock_sha256") or "").lower():
        errors.append("runtime manifest is bound to a different Python package lock")
    runtime_script_hashes = {
        (str(item.get("source")), str(item.get("relative_path"))): str(item.get("sha256") or "").lower()
        for item in (runtime.get("upstream_scripts") or [])
        if isinstance(item, Mapping)
    }
    locked_script_hashes = {
        (str(source.get("name")), str(relative).replace("\\", "/")): str(digest).lower()
        for source in (upstream_lock.get("sources") or [])
        for relative, digest in (source.get("script_sha256") or {}).items()
    }
    if runtime_script_hashes != locked_script_hashes:
        errors.append("runtime script snapshot does not match the current upstream lock")

    if compile_report.get("schema_version") != "travel-vlog-compile/1":
        errors.append("compile report schema is missing or unsupported")
    if compile_report.get("status") == "blocked" or compile_report.get("errors"):
        errors.append("latest compile report is blocked")
    if compile_report.get("published") is not True:
        errors.append("latest compile did not publish a complete artifact set")
    if current_plan_hash and compile_report.get("source_plan_sha256") != current_plan_hash:
        errors.append("compile report does not match the current story plan")
    if current_plan_hash and timeline.get("source_plan_sha256") != current_plan_hash:
        errors.append("timeline does not match the current story plan")
    expected_payload_hashes = compile_report.get("artifact_payload_sha256") or {}
    for filename, label in (
        ("compiled_transcript.json", "compiled_transcript"),
        ("vlog_timeline.json", "vlog_timeline"),
        ("render_config.json", "render_config"),
    ):
        if label in payloads and expected_payload_hashes.get(filename) != canonical_payload_sha256(payloads[label]):
            errors.append(f"{filename} differs from the latest successful compile")

    transcript_segments = [segment for segment in (transcript.get("segments") or []) if isinstance(segment, Mapping)]
    timeline_clips = [
        clip
        for section in (timeline.get("sections") or [])
        if isinstance(section, Mapping)
        for clip in (section.get("clips") or [])
        if isinstance(clip, Mapping)
    ]
    render_clips = [clip for clip in (render_config.get("clips") or []) if isinstance(clip, Mapping)]
    if not (len(transcript_segments) == len(timeline_clips) == len(render_clips)):
        errors.append("compiled transcript, timeline, and render config clip counts differ")
    for index, (segment, timeline_clip, render_clip) in enumerate(zip(transcript_segments, timeline_clips, render_clips), start=1):
        if segment.get("id") != timeline_clip.get("segment_id") or segment.get("id") != render_clip.get("segment_id"):
            errors.append(f"compiled segment ID mismatch at clip {index}")
        if Path(str(timeline_clip.get("render_source") or "")).resolve() != Path(str(render_clip.get("video") or "")).resolve():
            errors.append(f"timeline and render config proxy mismatch at clip {index}")
        if abs(float(segment.get("start") or 0) - float(timeline_clip.get("source_in") or 0)) > 1e-6:
            errors.append(f"timeline and transcript start mismatch at clip {index}")
        if abs(float(segment.get("end") or 0) - float(timeline_clip.get("source_out") or 0)) > 1e-6:
            errors.append(f"timeline and transcript end mismatch at clip {index}")

    if proxy_data.get("status") != "ready" or proxy_data.get("errors"):
        errors.append("proxy map is not ready")

    try:
        analysis = normalize_analysis(analysis_data, base_dir=artifact_paths["clip_analysis"].parent)
    except (ContractError, OSError) as exc:
        errors.append(f"clip analysis is invalid: {exc}")
        analysis = {"clips": []}
    analysis_by_source = {
        os.path.normcase(str(Path(str(clip.get("file") or "")).resolve())): clip
        for clip in (analysis.get("clips") or [])
        if clip.get("file")
    }
    inventory_by_source = {
        os.path.normcase(str(Path(str(item.get("project_path") or "")).resolve())): item
        for item in (inventory.get("files") or [])
        if item.get("project_path")
    }
    proxy_by_source = {
        os.path.normcase(str(Path(str(item.get("source") or "")).resolve())): item
        for item in (proxy_data.get("items") or [])
        if item.get("source")
    }
    config_videos = [
        Path(str(clip.get("video") or "")).resolve()
        for clip in (render_config.get("clips") or [])
        if isinstance(clip, Mapping) and clip.get("video")
    ]
    config_video_keys = {os.path.normcase(str(path)) for path in config_videos}
    media_entries: Dict[str, Dict[str, Any]] = {}
    selected_proxy_keys: set[str] = set()
    selected = selected_plan_clips(plan)
    for index, clip in enumerate(selected, start=1):
        try:
            source = resolve_plan_source(str(clip.get("file") or ""), project, plan_path.parent)
        except RuntimeError as exc:
            errors.append(f"selected clip {index}: {exc}")
            continue
        source_key = os.path.normcase(str(source.resolve()))
        if not path_is_within(source, project / "origin"):
            errors.append(f"selected source is outside the project origin directory: {source}")
        source_hash = hash_path(source)
        analysis_clip = analysis_by_source.get(source_key)
        inventory_item = inventory_by_source.get(source_key)
        if analysis_clip is None:
            errors.append(f"selected source is absent from clip analysis: {source}")
        if inventory_item is None:
            errors.append(f"selected source is absent from source inventory: {source}")
        for origin, expected in (
            ("clip analysis", (analysis_clip or {}).get("source_sha256")),
            ("source inventory", (inventory_item or {}).get("sha256")),
        ):
            if not expected:
                errors.append(f"{origin} has no source hash for: {source}")
            elif source_hash and str(expected).lower() != source_hash.lower():
                errors.append(f"source content changed after {origin}: {source}")
        if source_hash:
            media_entries[f"source:{source_key}"] = {
                "kind": "source",
                "path": str(source.resolve()),
                "sha256": source_hash,
                "bytes": source.stat().st_size,
            }

        proxy_item = proxy_by_source.get(source_key)
        if proxy_item is None or proxy_item.get("status") not in {"ready", "reused"}:
            errors.append(f"ready normalized proxy is missing for selected source: {source}")
            continue
        if source_hash and str(proxy_item.get("source_sha256") or "").lower() != source_hash.lower():
            errors.append(f"proxy source hash is stale: {source}")
        proxy = Path(str(proxy_item.get("proxy") or "")).resolve()
        if not path_is_within(proxy, work / "proxies"):
            errors.append(f"normalized proxy is outside the project proxy directory: {proxy}")
        proxy_hash = hash_path(proxy)
        expected_proxy_hash = str(proxy_item.get("proxy_sha256") or "").lower()
        if not expected_proxy_hash:
            errors.append(f"proxy map has no proxy hash: {proxy}")
        elif proxy_hash and expected_proxy_hash != proxy_hash.lower():
            errors.append(f"proxy content changed after normalization: {proxy}")
        proxy_key = os.path.normcase(str(proxy))
        selected_proxy_keys.add(proxy_key)
        if proxy_key not in config_video_keys:
            errors.append(f"selected proxy is absent from render config: {proxy}")
        if proxy_hash:
            media_entries[f"proxy:{proxy_key}"] = {
                "kind": "proxy",
                "path": str(proxy),
                "sha256": proxy_hash,
                "bytes": proxy.stat().st_size,
            }

    if len(config_videos) != len(selected):
        errors.append("render config clip count does not match the reviewed story plan")
    unexpected_config_videos = config_video_keys - selected_proxy_keys
    if unexpected_config_videos:
        errors.append("render config references media outside the selected normalized proxies")

    bgm_value = render_config.get("bgm")
    if bgm_value:
        bgm = Path(str(bgm_value)).resolve()
        if not path_is_within(bgm, project / "origin" / "bgm"):
            errors.append(f"BGM must be imported into the project origin/bgm directory: {bgm}")
        bgm_hash = hash_path(bgm)
        if bgm_hash:
            media_entries[f"bgm:{os.path.normcase(str(bgm))}"] = {
                "kind": "bgm", "path": str(bgm), "sha256": bgm_hash, "bytes": bgm.stat().st_size,
            }

    base_payload: Dict[str, Any] = {
        "schema_version": "travel-vlog-integrity/1",
        "project": str(project),
        "artifacts": artifacts,
        "vendor_trees": vendor_tree_records,
        "media": sorted(media_entries.values(), key=lambda item: (item["kind"], os.path.normcase(item["path"]))),
    }
    base_hash = canonical_payload_sha256(base_payload)
    base_payload["base_bundle_sha256"] = base_hash

    if require_preview:
        receipt_path = work / "technical_preview.json"
        receipt_hash = hash_path(receipt_path)
        if receipt_hash:
            artifacts["technical_preview"] = {
                "path": str(receipt_path.resolve()), "sha256": receipt_hash, "bytes": receipt_path.stat().st_size,
            }
        try:
            receipt = load_json(receipt_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"technical preview receipt is missing or unreadable: {exc}")
            receipt = {}
        config_hash = artifacts.get("render_config", {}).get("sha256")
        if receipt.get("schema_version") != "travel-vlog-render/2":
            errors.append("technical preview receipt schema is missing or unsupported")
        if receipt.get("preview") is not True:
            errors.append("technical preview receipt is not a preview")
        if receipt.get("status") != "pass" or (receipt.get("full_decode") or {}).get("status") != "pass":
            errors.append("technical preview did not pass its full-decode gate")
        requested_seconds = float(receipt.get("requested_seconds") or 0)
        if requested_seconds < 5.0 or requested_seconds > 8.0:
            errors.append("technical preview must cover 5 to 8 seconds")
        preview_media = receipt.get("media") or {}
        preview_duration = float(preview_media.get("duration") or 0)
        if (
            preview_media.get("video_codec") != "h264"
            or preview_media.get("pixel_format") != "yuv420p"
            or preview_media.get("audio_codec") != "aac"
            or preview_media.get("sample_rate") != 48000
            or preview_media.get("channels") != 2
            or preview_duration < 4.75
            or preview_duration > 8.25
        ):
            errors.append("technical preview media contract is invalid")
        if config_hash and receipt.get("source_render_config_sha256") != config_hash:
            errors.append("technical preview was rendered from a different render config")
        if receipt.get("source_bundle_sha256") != base_hash:
            errors.append("technical preview was rendered from a different integrity bundle")
        preview_config = Path(str(receipt.get("config") or "")).resolve()
        if not path_is_within(preview_config, work):
            errors.append(f"technical preview config is outside the project work directory: {preview_config}")
        preview_config_hash = hash_path(preview_config)
        if preview_config_hash and receipt.get("preview_config_sha256") != preview_config_hash:
            errors.append("technical preview config changed after rendering")
        if preview_config_hash:
            artifacts["preview_config"] = {
                "path": str(preview_config), "sha256": preview_config_hash, "bytes": preview_config.stat().st_size,
            }
        preview_transcript = Path(str(receipt.get("preview_transcript") or "")).resolve()
        if not path_is_within(preview_transcript, work):
            errors.append(f"technical preview transcript is outside the project work directory: {preview_transcript}")
        preview_transcript_hash = hash_path(preview_transcript)
        if preview_transcript_hash and receipt.get("preview_transcript_sha256") != preview_transcript_hash:
            errors.append("technical preview transcript changed after rendering")
        if preview_transcript_hash:
            artifacts["preview_transcript"] = {
                "path": str(preview_transcript), "sha256": preview_transcript_hash, "bytes": preview_transcript.stat().st_size,
            }
        preview = Path(str(receipt.get("output") or "")).resolve()
        if not path_is_within(preview, project / "output"):
            errors.append(f"technical preview is outside the project output directory: {preview}")
        preview_hash = hash_path(preview)
        if preview_hash and receipt.get("sha256") != preview_hash:
            errors.append("technical preview output changed after rendering")
        if preview_hash:
            media_entries[f"preview:{os.path.normcase(str(preview))}"] = {
                "kind": "technical_preview", "path": str(preview), "sha256": preview_hash, "bytes": preview.stat().st_size,
            }
        base_payload["media"] = sorted(media_entries.values(), key=lambda item: (item["kind"], os.path.normcase(item["path"])))

    base_payload["bundle_sha256"] = canonical_payload_sha256({key: value for key, value in base_payload.items() if key != "bundle_sha256"})
    return base_payload, list(dict.fromkeys(errors))


def approval_review_errors(plan: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    for index, clip in enumerate(selected_plan_clips(plan), start=1):
        if clip.get("visual_reviewed") is not True:
            errors.append(f"selected clip {index} has not been visually reviewed")
        if clip.get("needs_role_review") is True:
            errors.append(f"selected clip {index} still has an ambiguous story role")
    return errors


def cmd_approve(args: argparse.Namespace) -> int:
    project = resolve_project_path(args.project)
    plan_path = Path(args.plan).expanduser().resolve() if args.plan else project / "work" / "story_plan.json"
    canonical_plan = (project / "work" / "story_plan.json").resolve()
    if plan_path.resolve() != canonical_plan:
        print("Approval blocked: compile the reviewed plan into the project before approval.", file=sys.stderr)
        return 2
    plan = load_json(plan_path)
    review_errors = approval_review_errors(plan)
    bundle, integrity_errors = build_integrity_bundle(project, require_preview=True)
    blocking = review_errors + integrity_errors
    if blocking:
        print(json.dumps({"status": "blocked", "errors": blocking}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    missing = plan_missing_groups(plan)
    if missing and not args.accept_gaps:
        print("Coverage gaps remain; review them and rerun with --accept-gaps only after explicit user acceptance.", file=sys.stderr)
        return 2
    receipt = {
        "schema_version": "travel-vlog-story-approval/2",
        "approved_at": utc_now(),
        "decision": "approve",
        "reviewer": args.reviewer,
        "note": args.note or "",
        "plan": str(plan_path),
        "plan_sha256": story_plan_sha256(plan_path),
        "integrity_bundle_sha256": bundle["bundle_sha256"],
        "integrity_base_sha256": bundle["base_bundle_sha256"],
        "approved_artifacts": {
            label: {"sha256": item["sha256"], "bytes": item["bytes"]}
            for label, item in bundle["artifacts"].items()
        },
        "accepted_compile_warnings": list((load_json(project / "work" / "compile_report.json").get("warnings") or [])),
        "accepted_coverage_gaps": missing if args.accept_gaps else [],
    }
    output = project / "work" / "story_approval.json"
    if output.exists():
        backup_json(output, "pre-approval")
    write_json(output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def validate_renderer_contract(config_path: Path) -> List[str]:
    errors: List[str] = []
    try:
        config = load_json(config_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"render config unreadable: {exc}"]
    clips = config.get("clips")
    if not isinstance(clips, list) or not clips:
        return ["render config clips must be a non-empty array"]
    transcript_cache: Dict[str, Dict[Any, Mapping[str, Any]]] = {}
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, Mapping):
            errors.append(f"clip {index} is not an object")
            continue
        missing = [key for key in ("video", "transcript", "segment_id") if key not in clip]
        if missing:
            errors.append(f"clip {index} missing renderer fields: {', '.join(missing)}")
            continue
        video = Path(str(clip["video"]))
        transcript = Path(str(clip["transcript"]))
        if not video.is_absolute() or not transcript.is_absolute():
            errors.append(f"clip {index} must use absolute video and transcript paths")
        if not video.is_file():
            errors.append(f"clip {index} video not found: {video}")
        if not transcript.is_file():
            errors.append(f"clip {index} transcript not found: {transcript}")
            continue
        key = str(transcript.resolve())
        if key not in transcript_cache:
            try:
                payload = load_json(transcript)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"clip {index} transcript is unreadable: {exc}")
                continue
            transcript_cache[key] = {segment.get("id"): segment for segment in payload.get("segments") or [] if isinstance(segment, Mapping)}
        if clip["segment_id"] not in transcript_cache[key]:
            errors.append(f"clip {index} segment_id {clip['segment_id']!r} is absent with the same JSON type")
    return errors


def perform_preflight(project: Path, *, strict: bool = False) -> Tuple[int, Dict[str, Any]]:
    root = require_workspace_root()
    require_runtime_integrity(root)
    config = project / "work" / "render_config.json"
    verify = project / "verify"
    verify.mkdir(parents=True, exist_ok=True)
    integrity_bundle, integrity_errors = build_integrity_bundle(project, require_preview=False)
    contract_errors = validate_renderer_contract(config)
    upstream_json = verify / "edit_preflight.json"
    upstream_md = verify / "edit_preflight.md"
    result: Optional[subprocess.CompletedProcess[str]] = None
    if not integrity_errors and not contract_errors:
        result = run_upstream(
            root,
            "maxazure",
            "edit_preflight.py",
            ["--config", str(config), "--output", str(upstream_json), "--markdown", str(upstream_md), *( ["--strict"] if strict else [] )],
            cwd=root,
            capture=True,
        )
    upstream_report: Any = None
    if upstream_json.is_file():
        try:
            upstream_report = load_json(upstream_json)
        except (OSError, json.JSONDecodeError):
            upstream_report = None
    upstream_exit = result.returncode if result is not None else None
    upstream_errors: List[str] = []
    if result is not None and result.returncode == 0 and upstream_report is None:
        upstream_errors.append("MaxAzure preflight returned success without a readable report")
    report = {
        "schema_version": "travel-vlog-preflight/2",
        "generated_at": utc_now(),
        "status": "blocked" if integrity_errors or contract_errors or upstream_errors or upstream_exit != 0 else "ready",
        "strict": bool(strict),
        "integrity_bundle": integrity_bundle,
        "integrity_errors": integrity_errors,
        "renderer_contract_errors": contract_errors,
        "upstream_errors": upstream_errors,
        "upstream_exit": upstream_exit,
        "upstream_stdout": result.stdout if result is not None else "",
        "upstream_stderr": result.stderr if result is not None else "",
        "upstream_report": upstream_report,
    }
    write_json(verify / "fused_preflight.json", report)
    return (0 if report["status"] == "ready" else 2), report


def cmd_preflight(args: argparse.Namespace) -> int:
    code, report = perform_preflight(resolve_project_path(args.project), strict=args.strict)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


def make_preview_config(project: Path, seconds: float) -> Tuple[Path, Path]:
    config = load_json(project / "work" / "render_config.json")
    transcript = load_json(project / "work" / "compiled_transcript.json")
    by_id = {segment.get("id"): segment for segment in transcript.get("segments") or [] if isinstance(segment, Mapping)}
    preview_segments: List[Dict[str, Any]] = []
    preview_clips: List[Dict[str, Any]] = []
    remaining = max(1.0, seconds)
    new_id = 1
    for clip in config.get("clips") or []:
        segment = by_id.get(clip.get("segment_id"))
        if not segment or remaining <= 0:
            break
        duration = float(segment["end"]) - float(segment["start"])
        use = min(duration, remaining)
        if use <= 0:
            continue
        new_segment = copy.deepcopy(segment)
        new_segment["id"] = new_id
        new_segment["end"] = round(float(segment["start"]) + use, 3)
        preview_segments.append(new_segment)
        preview_clips.append({"video": clip["video"], "transcript": str((project / "work" / "compiled_transcript_preview.json").resolve()), "segment_id": new_id})
        remaining -= use
        new_id += 1
    if not preview_clips:
        raise RuntimeError("could not build a preview config")
    preview_transcript = copy.deepcopy(transcript)
    preview_transcript["segments"] = preview_segments
    preview_config = copy.deepcopy(config)
    preview_config["clips"] = preview_clips
    preview_config["versioned_output"] = False
    preview_config.pop("chapters", None)
    preview_config.pop("focus_events", None)
    transcript_path = project / "work" / "compiled_transcript_preview.json"
    config_path = project / "work" / "render_config_preview.json"
    write_json(transcript_path, preview_transcript)
    write_json(config_path, preview_config)
    return config_path, transcript_path


def cmd_render(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    project = resolve_project_path(args.project)
    preflight_code, preflight_report = perform_preflight(project, strict=True)
    if preflight_code != 0:
        print(json.dumps(preflight_report, ensure_ascii=False, indent=2), file=sys.stderr)
        return preflight_code
    plan_path = project / "work" / "story_plan.json"
    base_bundle = preflight_report["integrity_bundle"]
    approval_bundle: Optional[Dict[str, Any]] = None
    if not args.preview_seconds:
        approval_bundle, bundle_errors = build_integrity_bundle(project, require_preview=True)
        if bundle_errors:
            print(json.dumps({"status": "blocked", "errors": bundle_errors}, ensure_ascii=False, indent=2), file=sys.stderr)
            return 2
        approved, reason = validate_story_approval(
            plan_path,
            project / "work" / "story_approval.json",
            expected_bundle_sha256=approval_bundle["bundle_sha256"],
        )
        if not approved:
            print(f"Full render blocked: {reason}", file=sys.stderr)
            return 2
    config_path = project / "work" / "render_config.json"
    source_config_path = config_path
    source_config_hash = file_sha256(source_config_path)
    output_dir = project / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    title = str(load_json(config_path).get("title") or "travel-vlog")
    preview_transcript_path: Optional[Path] = None
    if args.preview_seconds:
        config_path, preview_transcript_path = make_preview_config(project, args.preview_seconds)
        output = next_versioned_path(output_dir / f"preview_{int(round(args.preview_seconds))}s.mp4")
    elif args.output:
        output = Path(args.output).expanduser().resolve()
    else:
        output = output_dir / f"{safe_stem(title)}_master.mp4"
    if output.suffix.lower() != ".mp4" or not path_is_within(output, output_dir):
        print(f"Render output must be an MP4 inside the project output directory: {output}", file=sys.stderr)
        return 2
    first_video = Path(str(load_json(config_path)["clips"][0]["video"]))
    media = probe_media(first_video, root)
    font_size = 80 if media["height"] > media["width"] else 58
    font_path = find_cjk_font()
    render_args = [
        "--config", str(config_path), "--output", str(output), "--primary-speed", "1.0",
        "--no-cover", "--cleanup", "--font-size", str(font_size),
    ]
    if font_path:
        render_args.extend(["--font-path", str(font_path)])
    if args.platform != "xhs":
        render_args.append("--no-content-guard")
    maxazure, _ = vendor_paths(root)
    render_nonce = uuid.uuid4().hex
    bridge_result_path = project / "work" / "render-results" / f"{render_nonce}.json"
    bridge_result_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_render_lock(project):
        require_runtime_integrity(root)
        result = run_command(
            [
                sys.executable,
                "-X", "utf8", "-s", "-B",
                str(skill_dir() / "scripts" / "render_bridge.py"),
                "--vendor-scripts", str(maxazure / "scripts"),
                "--encoder", args.encoder,
                "--result-json", str(bridge_result_path),
                "--nonce", render_nonce,
                *render_args,
            ],
            cwd=root,
            root=root,
        )
    if result.returncode != 0:
        return result.returncode
    try:
        bridge_result = load_json(bridge_result_path)
        rendered = Path(str(bridge_result.get("actual_output") or "")).resolve()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Renderer result receipt is unreadable: {exc}", file=sys.stderr)
        return 2
    if bridge_result.get("schema_version") != "travel-vlog-render-bridge/1" or bridge_result.get("nonce") != render_nonce:
        print("Renderer result receipt schema or nonce is invalid.", file=sys.stderr)
        return 2
    if Path(str(bridge_result.get("requested_output") or "")).resolve() != output.resolve():
        print("Renderer result receipt does not match the requested output.", file=sys.stderr)
        return 2
    if (
        bridge_result.get("returncode") != 0
        or bridge_result.get("failure")
        or bridge_result.get("preexisting") is not False
        or not bridge_result.get("exists")
        or not rendered.is_file()
    ):
        print("Renderer did not attribute an exact output file.", file=sys.stderr)
        return 2
    if not path_is_within(rendered, output_dir):
        print(f"Renderer output escaped the project output directory: {rendered}", file=sys.stderr)
        return 2
    requested_family = re.sub(r"_V\d+$", "", output.stem)
    rendered_family = re.sub(r"_V\d+$", "", rendered.stem)
    if rendered.parent != output.parent or rendered.suffix.lower() != output.suffix.lower() or rendered_family != requested_family:
        print("Renderer output does not belong to the requested versioned output family.", file=sys.stderr)
        return 2
    if rendered.stat().st_size < 1024:
        print(f"Rendered file is unexpectedly small: {rendered}", file=sys.stderr)
        return 2
    rendered_media = probe_media(rendered, root)
    decoded, decode_detail = decode_media(rendered, root)
    if not decoded:
        print(f"Rendered file failed full decode: {decode_detail}", file=sys.stderr)
        return 2
    receipt = {
        "schema_version": "travel-vlog-render/2",
        "rendered_at": utc_now(),
        "preview": bool(args.preview_seconds),
        "config": str(config_path),
        "source_render_config": str(source_config_path),
        "source_render_config_sha256": source_config_hash,
        "source_plan_sha256": story_plan_sha256(plan_path),
        "source_bundle_sha256": base_bundle["base_bundle_sha256"],
        "preview_config_sha256": file_sha256(config_path) if args.preview_seconds else None,
        "preview_transcript": str(preview_transcript_path) if preview_transcript_path else None,
        "preview_transcript_sha256": file_sha256(preview_transcript_path) if preview_transcript_path else None,
        "approved_bundle_sha256": approval_bundle["bundle_sha256"] if approval_bundle else None,
        "approval_receipt_sha256": file_sha256(project / "work" / "story_approval.json") if approval_bundle else None,
        "bridge_result_sha256": file_sha256(bridge_result_path),
        "output": str(rendered.resolve()),
        "sha256": file_sha256(rendered),
        "bytes": rendered.stat().st_size,
        "media": rendered_media,
        "full_decode": {"status": "pass", "detail": decode_detail},
        "status": "pass" if args.preview_seconds else "rendered_unverified",
    }
    if args.preview_seconds:
        receipt["requested_seconds"] = float(args.preview_seconds)
        write_json(project / "work" / "technical_preview.json", receipt)
    else:
        write_json(project / "work" / "last_render.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    root = require_workspace_root()
    require_runtime_integrity(root)
    ffmpeg, _ = find_ffmpeg_tools(root)
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required for full decode QA")
    project = resolve_project_path(args.project)
    video = Path(args.video).expanduser().resolve()
    if not video.is_file():
        raise RuntimeError(f"video not found: {video}")
    if not path_is_within(video, project / "output"):
        print("QA blocked: video must be inside the project output directory.", file=sys.stderr)
        return 2
    render_receipt_path = project / "work" / "last_render.json"
    try:
        render_receipt = load_json(render_receipt_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"QA blocked: full render receipt is missing or unreadable: {exc}", file=sys.stderr)
        return 2
    actual_video_hash = file_sha256(video)
    if (
        render_receipt.get("schema_version") != "travel-vlog-render/2"
        or render_receipt.get("preview") is not False
        or Path(str(render_receipt.get("output") or "")).resolve() != video
        or render_receipt.get("sha256") != actual_video_hash
    ):
        print("QA blocked: video does not match the current full render receipt.", file=sys.stderr)
        return 2
    bundle, bundle_errors = build_integrity_bundle(project, require_preview=True)
    if bundle_errors:
        print(json.dumps({"status": "blocked", "errors": bundle_errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    approval_path = project / "work" / "story_approval.json"
    approved, reason = validate_story_approval(
        project / "work" / "story_plan.json",
        approval_path,
        expected_bundle_sha256=bundle["bundle_sha256"],
    )
    approval_hash_matches = approval_path.is_file() and render_receipt.get("approval_receipt_sha256") == file_sha256(approval_path)
    if not approved or render_receipt.get("approved_bundle_sha256") != bundle["bundle_sha256"] or not approval_hash_matches:
        print(f"QA blocked: {reason if not approved else 'full render used a stale integrity bundle'}", file=sys.stderr)
        return 2
    verify = project / "verify" / "qa" / actual_video_hash[:16]
    verify.mkdir(parents=True, exist_ok=True)
    sink = "NUL" if os.name == "nt" else "/dev/null"
    decode = run_command(
        [str(ffmpeg), "-nostdin", "-v", "error", "-xerror", "-i", str(video), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", sink],
        root=root,
        capture=True,
    )
    (verify / "full_decode.txt").write_text((decode.stderr or decode.stdout or "OK") + "\n", encoding="utf-8")
    qa_args = [str(video), "--json", str(verify / "render_qa.json"), "--review-dir", str(verify / "review")]
    if args.platform in {"xhs", "douyin", "wxch"}:
        qa_args += ["--platform", args.platform]
    if args.review_clips:
        qa_args.append("--review-clips")
    qa = run_upstream(root, "maxazure", "render_qa.py", qa_args, cwd=root)
    qa_report = load_json(verify / "render_qa.json") if (verify / "render_qa.json").is_file() else None
    upstream_status = str((qa_report or {}).get("status") or "missing")
    if decode.returncode == 0 and qa.returncode == 0 and upstream_status == "pass":
        status = "pass"
    elif upstream_status == "warn":
        status = "warn"
    else:
        status = "fail"
    report = {
        "schema_version": "travel-vlog-final-qa/2",
        "generated_at": utc_now(),
        "status": status,
        "video": str(video),
        "video_sha256": actual_video_hash,
        "integrity_bundle_sha256": bundle["bundle_sha256"],
        "full_render_receipt": str(render_receipt_path),
        "full_render_receipt_sha256": file_sha256(render_receipt_path),
        "full_decode_exit": decode.returncode,
        "full_decode_log": str(verify / "full_decode.txt"),
        "maxazure_qa_exit": qa.returncode,
        "maxazure_report": str(verify / "render_qa.json"),
        "maxazure_report_sha256": file_sha256(verify / "render_qa.json") if (verify / "render_qa.json").is_file() else None,
        "human_review_required": True,
    }
    write_json(verify / "final_qa.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "pass" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fused travel and food Vlog editing pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check runtime and pinned source integrity")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--require-asr", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    prepare = subparsers.add_parser("prepare", help="Bootstrap an edit project and analysis template")
    prepare.add_argument("--source", action="append", required=True)
    prepare.add_argument("--project", required=True)
    prepare.add_argument("--profile", choices=["food", "travel"], default="travel")
    prepare.add_argument("--title", required=True)
    prepare.add_argument("--target-duration", type=float, default=120.0)
    prepare.add_argument("--mode", choices=["copy", "hardlink"], default="copy")
    prepare.add_argument("--reimport", action="store_true")
    prepare.add_argument("--rebuild-analysis", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    frames = subparsers.add_parser("frames", help="Extract representative review frames")
    frames.add_argument("--analysis", required=True)
    frames.add_argument("--out", required=True)
    frames.add_argument("--max-clips", type=int)
    frames.add_argument("--force", action="store_true")
    frames.set_defaults(func=cmd_frames)

    transcribe = subparsers.add_parser("transcribe", help="Run local faster-whisper for selected clips")
    transcribe.add_argument("--analysis", required=True)
    transcribe.add_argument("--project", required=True)
    transcribe.add_argument("--language", default="zh")
    transcribe.add_argument("--model", default="small")
    transcribe.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    transcribe.add_argument("--compute-type", default="int8")
    transcribe.add_argument("--word-timestamps", action="store_true")
    transcribe.add_argument("--all", action="store_true")
    transcribe.add_argument("--limit", type=int)
    transcribe.set_defaults(func=cmd_transcribe)

    classify = subparsers.add_parser("classify", help="Apply deterministic Vlog taxonomy")
    classify.add_argument("--analysis", required=True)
    classify.add_argument("--profile", choices=["food", "travel"], default="travel")
    classify.add_argument("--output")
    classify.add_argument("--force", action="store_true")
    classify.set_defaults(func=cmd_classify)

    plan = subparsers.add_parser("plan", help="Build a first-pass reviewable story plan")
    plan.add_argument("--analysis", required=True)
    plan.add_argument("--profile", choices=["food", "travel"], default="travel")
    plan.add_argument("--target-duration", type=float)
    plan.add_argument("--title")
    plan.add_argument("--output", required=True)
    plan.set_defaults(func=cmd_plan)

    review = subparsers.add_parser("review", help="Generate upstream storyboard and dashboard")
    review.add_argument("--analysis", required=True)
    review.add_argument("--plan", required=True)
    review.add_argument("--footage", required=True)
    review.add_argument("--out", required=True)
    review.set_defaults(func=cmd_review)

    normalize = subparsers.add_parser("normalize", help="Normalize selected sources to concat-safe proxies")
    normalize.add_argument("--plan", required=True)
    normalize.add_argument("--project", required=True)
    normalize.add_argument("--width", type=int, default=1920)
    normalize.add_argument("--height", type=int, default=1080)
    normalize.add_argument("--fps", type=float, default=30.0)
    normalize.add_argument("--fit", choices=["contain", "crop"], default="contain")
    normalize.add_argument("--force", action="store_true")
    normalize.set_defaults(func=cmd_normalize)

    compile_parser = subparsers.add_parser("compile", help="Compile story plan to MaxAzure artifacts")
    compile_parser.add_argument("--analysis", required=True)
    compile_parser.add_argument("--plan", required=True)
    compile_parser.add_argument("--project", required=True)
    compile_parser.add_argument("--proxy-map")
    compile_parser.add_argument("--bgm")
    compile_parser.set_defaults(func=cmd_compile)

    approve = subparsers.add_parser("approve", help="Record explicit user approval bound to the exact integrity bundle")
    approve.add_argument("--project", required=True)
    approve.add_argument("--plan")
    approve.add_argument("--reviewer", default="user")
    approve.add_argument("--note")
    approve.add_argument("--accept-gaps", action="store_true")
    approve.set_defaults(func=cmd_approve)

    preflight = subparsers.add_parser("preflight", help="Run fused renderer-contract and MaxAzure preflight")
    preflight.add_argument("--project", required=True)
    preflight.add_argument("--strict", action="store_true")
    preflight.set_defaults(func=cmd_preflight)

    render = subparsers.add_parser("render", help="Render technical preview or approved full master")
    render.add_argument("--project", required=True)
    render.add_argument("--preview-seconds", type=float)
    render.add_argument("--output")
    render.add_argument("--platform", choices=["bilibili", "youtube", "xhs", "douyin", "wxch"], default="bilibili")
    render.add_argument("--encoder", choices=["libx264", "auto"], default="libx264")
    render.set_defaults(func=cmd_render)

    qa = subparsers.add_parser("qa", help="Run full decode and MaxAzure post-render QA")
    qa.add_argument("--project", required=True)
    qa.add_argument("--video", required=True)
    qa.add_argument("--platform", choices=["bilibili", "youtube", "xhs", "douyin", "wxch"], default="bilibili")
    qa.add_argument("--review-clips", action="store_true")
    qa.set_defaults(func=cmd_qa)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    if os.environ.get("TRAVEL_VLOG_SECURE_LAUNCH") != "1":
        print(
            "Error: direct pipeline.py execution is unsupported; use scripts/run_pipeline.ps1 so bytecode is rejected before Python starts.",
            file=sys.stderr,
        )
        return 2
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ContractError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
