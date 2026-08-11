#!/usr/bin/env python3
"""Deterministic data layer for the Travel Vlog Pipeline."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ANALYSIS_VERSION = "travel-vlog-analysis/1"
STORY_VERSION = "travel-vlog-story/1"
TIMELINE_VERSION = "vlog-timeline/1"
COMPILE_VERSION = "travel-vlog-compile/1"

ROLE_KEYWORDS: Dict[str, Sequence[str]] = {
    "arrival": (
        "到达", "到了", "抵达", "终于到", "到店", "下车", "arrival", "arrived",
        "reach", "approach",
    ),
    "exterior": (
        "门头", "招牌", "店外", "外观", "门面", "排队", "街边", "storefront",
        "exterior", "signboard", "queue", "outside",
    ),
    "entry": (
        "进店", "进门", "进去", "入店", "推门", "门口进入", "enter", "entry",
        "walk in", "inside transition",
    ),
    "environment": (
        "环境", "店内", "装修", "座位", "大厅", "包间", "氛围", "室内", "餐厅全景",
        "interior", "environment", "decor", "seating", "atmosphere", "room",
    ),
    "ordering": (
        "点单", "点菜", "菜单", "价格", "套餐", "推荐菜", "下单", "扫码点餐",
        "order", "ordering", "menu", "price", "choose dish",
    ),
    "serving": (
        "上菜", "上桌", "端上", "出餐", "开盖", "摆盘", "端来", "serve", "serving",
        "arrives", "plating", "uncover",
    ),
    "food_action": (
        "夹起", "夹菜", "切开", "搅拌", "拉丝", "冒热气", "蘸", "倒入", "撕开",
        "切肉", "翻面", "pour", "cut", "mix", "steam", "dip", "lift", "sizzle",
    ),
    "tasting_reaction": (
        "品尝", "试吃", "入口", "好吃", "味道", "口感", "香", "很辣", "很甜", "评价",
        "反应", "taste", "tasting", "flavor", "texture", "delicious", "reaction",
    ),
    "summary_exit": (
        "总结", "推荐", "性价比", "买单", "结账", "离店", "离开", "回去", "下次再来",
        "吃完", "结束", "summary", "conclusion", "recommend", "bill", "checkout", "exit",
        "leave", "ending",
    ),
    "transit": (
        "火车", "高铁", "地铁", "公交", "飞机", "机场", "车站", "打车", "走路", "路上",
        "出发", "station", "train", "metro", "bus", "plane", "airport", "taxi", "road",
        "transit", "depart",
    ),
    "scenic_transition": (
        "风景", "街景", "建筑", "日落", "夜景", "远景", "城市", "山", "海", "湖", "景点",
        "landscape", "scenery", "street view", "architecture", "sunset", "city view",
    ),
    "people_interaction": (
        "合影", "聊天", "朋友", "服务员", "店员", "笑", "人群", "互动", "碰杯", "自拍",
        "people", "person", "friend", "staff", "chat", "laugh", "interaction", "selfie",
    ),
    "food_hero": (
        "菜品", "食物", "美食", "特写", "锅", "饭", "面", "肉", "鱼", "甜品", "蛋糕",
        "咖啡", "饮料", "小吃", "火锅", "烧烤", "dish", "food", "meal", "dessert",
        "drink", "close-up", "closeup",
    ),
}

ROLE_ORDER = [
    "arrival", "exterior", "entry", "environment", "ordering", "serving",
    "food_hero", "food_action", "tasting_reaction", "people_interaction",
    "transit", "scenic_transition", "summary_exit", "other",
]

ROLE_CONTENT_CLASS = {
    "food_hero": "food",
    "food_action": "food",
    "serving": "food",
    "tasting_reaction": "people",
    "people_interaction": "people",
    "scenic_transition": "scenery",
    "environment": "scenery",
    "exterior": "scenery",
    "arrival": "daily_transit",
    "transit": "daily_transit",
    "entry": "daily_transit",
    "ordering": "daily_transit",
    "summary_exit": "daily_transit",
    "other": "other",
}

TARGET_SHOT_SECONDS = {
    "arrival": 3.5,
    "exterior": 3.5,
    "entry": 3.0,
    "environment": 4.0,
    "ordering": 4.5,
    "serving": 4.0,
    "food_hero": 4.8,
    "food_action": 5.0,
    "tasting_reaction": 6.0,
    "people_interaction": 4.5,
    "transit": 3.5,
    "scenic_transition": 4.0,
    "summary_exit": 5.5,
    "other": 3.5,
}


class ContractError(ValueError):
    """Raised when an artifact violates the integration contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: os.PathLike[str] | str) -> Any:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: os.PathLike[str] | str, value: Any) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def file_sha256(path: os.PathLike[str] | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_json(path: os.PathLike[str] | str, action: str) -> Optional[Path]:
    source = Path(path)
    if not source.is_file():
        return None
    history = source.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    destination = history / f"{source.stem}-{action}-{stamp}{source.suffix}"
    counter = 2
    while destination.exists():
        destination = history / f"{source.stem}-{action}-{stamp}-{counter}{source.suffix}"
        counter += 1
    destination.write_bytes(source.read_bytes())
    return destination


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, as_float(value))
    text = str(value or "").strip()
    if not text:
        return 0.0
    if ":" not in text:
        return max(0.0, as_float(text))
    parts = text.split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return 0.0
    if len(numbers) == 2:
        return max(0.0, numbers[0] * 60 + numbers[1])
    if len(numbers) == 3:
        return max(0.0, numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
    return 0.0


def parse_resolution(value: Any) -> Tuple[int, int]:
    match = re.match(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$", str(value or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _normalize_transcript(items: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return normalized
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            continue
        start = round(parse_time(item.get("start")), 3)
        end = round(parse_time(item.get("end")), 3)
        if end <= start:
            continue
        entry: Dict[str, Any] = {
            "id": item.get("id", index),
            "start": start,
            "end": end,
            "text": str(item.get("text") or "").strip(),
        }
        words = item.get("words")
        if isinstance(words, list):
            entry["words"] = copy.deepcopy(words)
        normalized.append(entry)
    return normalized


def normalize_analysis(data: Any, *, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    if isinstance(data, list):
        project: Dict[str, Any] = {}
        raw_clips = data
    elif isinstance(data, Mapping):
        project = copy.deepcopy(data.get("project") or {})
        raw_clips = data.get("clips")
        if raw_clips is None and isinstance(data.get("items"), list):
            raw_clips = data.get("items")
    else:
        raise ContractError("clip analysis must be a JSON object or array")
    if not isinstance(raw_clips, list):
        raise ContractError("clip analysis has no clips array")

    clips: List[Dict[str, Any]] = []
    for index, raw in enumerate(raw_clips):
        if not isinstance(raw, Mapping):
            continue
        raw_file = raw.get("file") or raw.get("filename") or raw.get("path")
        if not raw_file:
            raise ContractError(f"clip #{index + 1} has no file/filename/path")
        file_path = Path(str(raw_file)).expanduser()
        if not file_path.is_absolute() and base_dir is not None:
            candidate = (base_dir / file_path).resolve()
            if candidate.exists():
                file_path = candidate
        try:
            file_text = str(file_path.resolve())
        except OSError:
            file_text = str(file_path)

        width = int(as_float(raw.get("width"), 0))
        height = int(as_float(raw.get("height"), 0))
        if width <= 0 or height <= 0:
            width, height = parse_resolution(raw.get("resolution"))
        duration = max(0.0, as_float(raw.get("duration"), 0.0))

        visual: List[Dict[str, Any]] = []
        raw_visual = raw.get("visual")
        if isinstance(raw_visual, str):
            raw_visual = [{"time": 0.0, "description": raw_visual}]
        if isinstance(raw_visual, list):
            for visual_item in raw_visual:
                if not isinstance(visual_item, Mapping):
                    continue
                tags = visual_item.get("tags") or []
                if isinstance(tags, str):
                    tags = [token.strip() for token in re.split(r"[,，;；]", tags) if token.strip()]
                visual.append({
                    "time": round(parse_time(visual_item.get("time")), 3),
                    "description": str(visual_item.get("description") or "").strip(),
                    "shot_type": str(visual_item.get("shot_type") or "").strip(),
                    "camera": str(visual_item.get("camera") or "").strip(),
                    "mood": str(visual_item.get("mood") or "").strip(),
                    "tags": list(tags) if isinstance(tags, list) else [],
                })

        raw_audio = raw.get("audio") if isinstance(raw.get("audio"), Mapping) else {}
        transcript = _normalize_transcript(raw_audio.get("transcript") or raw.get("speech") or [])
        has_speech_raw = raw_audio.get("has_speech")
        has_speech = bool(has_speech_raw) if has_speech_raw is not None else bool(transcript)
        audio: Dict[str, Any] = {
            "has_track": bool(raw_audio.get("has_track", raw.get("has_audio", True))),
            "has_speech": has_speech,
            "mean_volume_db": raw_audio.get("mean_volume_db"),
            "max_volume_db": raw_audio.get("max_volume_db"),
            "transcript": transcript,
        }
        if raw_audio.get("transcript_path"):
            audio["transcript_path"] = str(raw_audio["transcript_path"])

        preprocessing = copy.deepcopy(raw.get("preprocessing") or {})
        recommended = preprocessing.get("recommended_range")
        if not (isinstance(recommended, list) and len(recommended) == 2):
            recommended = [0.0, duration]
        rec_start = clamp(as_float(recommended[0]), 0.0, duration)
        rec_end = clamp(as_float(recommended[1], duration), 0.0, duration)
        if rec_end <= rec_start:
            rec_start, rec_end = 0.0, duration
        preprocessing["recommended_range"] = [round(rec_start, 3), round(rec_end, 3)]
        preprocessing.setdefault("mode", "normal")
        preprocessing.setdefault("skip_zones", [])

        labels = copy.deepcopy(raw.get("labels") or {})
        labels.setdefault("story_role", "unclassified")
        labels.setdefault("content_class", "unclassified")
        labels.setdefault("quality", raw.get("quality"))
        labels.setdefault("keep", True)
        labels.setdefault("human_override", False)

        clip = copy.deepcopy(dict(raw))
        clip.update({
            "file": file_text,
            "filename": Path(file_text).name,
            "duration": round(duration, 3),
            "width": width,
            "height": height,
            "fps": round(as_float(raw.get("fps"), 0.0), 3),
            "resolution": f"{width}x{height}" if width and height else str(raw.get("resolution") or ""),
            "visual": visual,
            "audio": audio,
            "preprocessing": preprocessing,
            "labels": labels,
            "source_index": int(raw.get("source_index", index)),
        })
        clips.append(clip)

    return {
        "schema_version": ANALYSIS_VERSION,
        "generated_at": str(data.get("generated_at") or utc_now()) if isinstance(data, Mapping) else utc_now(),
        "project": project,
        "clips": clips,
    }


def _text_parts(clip: Mapping[str, Any]) -> Tuple[str, str, str]:
    filename = Path(str(clip.get("file") or "")).stem.lower()
    visual_parts: List[str] = []
    for item in clip.get("visual") or []:
        if isinstance(item, Mapping):
            visual_parts.extend([
                str(item.get("description") or ""),
                str(item.get("shot_type") or ""),
                str(item.get("camera") or ""),
                str(item.get("mood") or ""),
                " ".join(str(tag) for tag in item.get("tags") or []),
            ])
    speech = " ".join(
        str(item.get("text") or "")
        for item in (clip.get("audio") or {}).get("transcript") or []
        if isinstance(item, Mapping)
    )
    return filename, " ".join(visual_parts).lower(), speech.lower()


def _keyword_score(text: str, keywords: Iterable[str], weight: float) -> Tuple[float, List[str]]:
    score = 0.0
    matches: List[str] = []
    for keyword in keywords:
        token = keyword.lower()
        if token and token in text:
            score += weight * (1.25 if len(token) >= 4 else 1.0)
            matches.append(keyword)
    return score, matches


def infer_role(clip: Mapping[str, Any]) -> Tuple[str, float, List[str]]:
    filename, visual, speech = _text_parts(clip)
    scores: Dict[str, float] = {}
    reasons: Dict[str, List[str]] = {}
    for role, keywords in ROLE_KEYWORDS.items():
        visual_score, visual_matches = _keyword_score(visual, keywords, 1.0)
        speech_score, speech_matches = _keyword_score(speech, keywords, 0.85)
        file_score, file_matches = _keyword_score(filename, keywords, 0.3)
        score = visual_score + speech_score + file_score
        scores[role] = score
        reasons[role] = list(dict.fromkeys(visual_matches + speech_matches + file_matches))[:8]

    if not scores or max(scores.values()) <= 0:
        return "other", 0.0, []
    order_rank = {role: index for index, role in enumerate(ROLE_ORDER)}
    role = max(scores, key=lambda item: (scores[item], -order_rank.get(item, 999)))
    total = sum(scores.values())
    confidence = clamp(scores[role] / total if total else 0.0, 0.0, 1.0)
    return role, round(confidence, 3), reasons.get(role, [])


def estimate_quality(clip: Mapping[str, Any]) -> float:
    supplied = (clip.get("labels") or {}).get("quality")
    if supplied is not None:
        return round(clamp(as_float(supplied, 0.5), 0.0, 1.0), 3)
    score = 0.5
    width = int(as_float(clip.get("width"), 0))
    height = int(as_float(clip.get("height"), 0))
    if max(width, height) >= 1920 and min(width, height) >= 1080:
        score += 0.06
    duration = as_float(clip.get("duration"), 0.0)
    if 1.5 <= duration <= 30:
        score += 0.05
    if clip.get("visual"):
        score += 0.08
    camera_text = " ".join(str(item.get("camera") or "") for item in clip.get("visual") or [] if isinstance(item, Mapping)).lower()
    description_text = " ".join(str(item.get("description") or "") for item in clip.get("visual") or [] if isinstance(item, Mapping)).lower()
    if any(token in camera_text for token in ("固定", "稳定", "tripod", "stable")):
        score += 0.08
    if any(token in f"{camera_text} {description_text}" for token in ("剧烈晃", "严重抖", "模糊", "失焦", "shaky", "blur", "out of focus")):
        score -= 0.18
    skip_zones = (clip.get("preprocessing") or {}).get("skip_zones") or []
    if len(skip_zones) >= 2:
        score -= 0.05
    return round(clamp(score, 0.05, 0.98), 3)


def classify_analysis(data: Any, *, profile: str, force: bool = False, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    normalized = normalize_analysis(data, base_dir=base_dir)
    for clip in normalized["clips"]:
        labels = clip["labels"]
        existing_role = str(labels.get("story_role") or "").strip()
        preserve = existing_role in ROLE_ORDER and existing_role != "other" and not force
        if labels.get("human_override") and existing_role in ROLE_ORDER:
            preserve = True
        if preserve:
            role = existing_role
            confidence = as_float(labels.get("confidence"), 1.0 if labels.get("human_override") else 0.75)
            reasons = list(labels.get("reasons") or ["existing label preserved"])
        else:
            role, confidence, reasons = infer_role(clip)
        content_class = str(labels.get("content_class") or "")
        if force or content_class not in {"food", "scenery", "people", "daily_transit", "other"}:
            content_class = ROLE_CONTENT_CLASS.get(role, "other")
        labels.update({
            "story_role": role,
            "content_class": content_class,
            "confidence": round(confidence, 3),
            "quality": estimate_quality(clip),
            "reasons": reasons,
            "classifier": "travel-vlog-keywords/1",
            "needs_role_review": bool(not labels.get("human_override") and (role == "other" or confidence < 0.65)),
        })
        if role == "food_hero" and as_float(clip.get("duration")) >= 3.5:
            camera = " ".join(str(item.get("camera") or "") for item in clip.get("visual") or [] if isinstance(item, Mapping)).lower()
            unstable_camera_tokens = ("handheld", "shaky", "\u624b\u6301", "\u5267\u70c8", "\u6296\u52a8")
            if not any(token in camera for token in unstable_camera_tokens):
                labels.setdefault("motion_hint", "subtle_push")
        clip["labels"] = labels
    normalized["project"]["profile"] = profile
    normalized["classified_at"] = utc_now()
    return normalized


def load_profile(path: os.PathLike[str] | str) -> Dict[str, Any]:
    profile = load_json(path)
    if not isinstance(profile, Mapping) or not isinstance(profile.get("sections"), list):
        raise ContractError(f"invalid profile: {path}")
    return copy.deepcopy(dict(profile))


def _best_anchor(clip: Mapping[str, Any], role: str, start: float, end: float) -> float:
    keywords = ROLE_KEYWORDS.get(role, ())
    best = (0.0, start)
    for visual in clip.get("visual") or []:
        if not isinstance(visual, Mapping):
            continue
        at = clamp(parse_time(visual.get("time")), start, end)
        text = " ".join([
            str(visual.get("description") or ""),
            " ".join(str(tag) for tag in visual.get("tags") or []),
        ]).lower()
        score, _ = _keyword_score(text, keywords, 1.0)
        if score > best[0]:
            best = (score, at)
    return best[1]


def choose_source_range(clip: Mapping[str, Any], role: str) -> Tuple[float, float, str]:
    duration = as_float(clip.get("duration"), 0.0)
    recommended = (clip.get("preprocessing") or {}).get("recommended_range") or [0.0, duration]
    start = clamp(as_float(recommended[0]), 0.0, duration)
    end = clamp(as_float(recommended[1], duration), start, duration)
    if end - start < 0.5:
        start, end = 0.0, duration
    target = min(TARGET_SHOT_SECONDS.get(role, 3.5), max(0.5, end - start))
    transcript = (clip.get("audio") or {}).get("transcript") or []

    if transcript:
        role_keywords = ROLE_KEYWORDS.get(role, ())
        scored: List[Tuple[float, int, Mapping[str, Any]]] = []
        for index, segment in enumerate(transcript):
            if not isinstance(segment, Mapping):
                continue
            seg_start = as_float(segment.get("start"))
            seg_end = as_float(segment.get("end"))
            if seg_end <= start or seg_start >= end:
                continue
            text_score, _ = _keyword_score(str(segment.get("text") or "").lower(), role_keywords, 1.0)
            scored.append((text_score, -index, segment))
        if scored:
            segment = max(scored, key=lambda item: (item[0], item[1]))[2]
            cut_start = clamp(as_float(segment.get("start")) - 0.2, start, end)
            desired_end = max(cut_start + target, as_float(segment.get("end")) + 0.2)
            cut_end = clamp(desired_end, cut_start + 0.1, end)
            if cut_end - cut_start < target and cut_start > start:
                cut_start = max(start, cut_end - target)
            subtitle = " ".join(
                str(item.get("text") or "").strip()
                for item in transcript
                if isinstance(item, Mapping)
                and as_float(item.get("end")) > cut_start
                and as_float(item.get("start")) < cut_end
                and str(item.get("text") or "").strip()
            )
            return round(cut_start, 1), round(cut_end, 1), subtitle

    if role == "summary_exit":
        cut_end = end
        cut_start = max(start, cut_end - target)
    else:
        anchor = _best_anchor(clip, role, start, end)
        cut_start = clamp(anchor - target / 2, start, max(start, end - target))
        cut_end = min(end, cut_start + target)
    return round(cut_start, 1), round(cut_end, 1), ""


def _clip_note(clip: Mapping[str, Any], role: str) -> str:
    visual = clip.get("visual") or []
    if visual and isinstance(visual[0], Mapping):
        description = str(visual[0].get("description") or "").strip()
        if description:
            return description[:60]
    return f"{role}: {Path(str(clip.get('file') or '')).name}"


def _make_candidate(clip: Mapping[str, Any]) -> Dict[str, Any]:
    labels = clip.get("labels") or {}
    role = str(labels.get("story_role") or "other")
    if role not in ROLE_ORDER:
        role = "other"
    start, end, subtitle = choose_source_range(clip, role)
    if end <= start:
        raise ContractError(f"no usable interval for {clip.get('file')}")
    visual = clip.get("visual") or []
    first_visual = visual[0] if visual and isinstance(visual[0], Mapping) else {}
    return {
        "candidate_id": f"c{int(clip.get('source_index', 0)) + 1:04d}",
        "file": str(clip.get("file")),
        "start": start,
        "end": end,
        "note": _clip_note(clip, role),
        "subtitle": subtitle,
        "story_role": role,
        "content_class": str(labels.get("content_class") or ROLE_CONTENT_CLASS.get(role, "other")),
        "shot_type": str(first_visual.get("shot_type") or ""),
        "camera": str(first_visual.get("camera") or ""),
        "mood": str(first_visual.get("mood") or ""),
        "quality": round(as_float(labels.get("quality"), 0.5), 3),
        "confidence": round(as_float(labels.get("confidence"), 0.0), 3),
        "needs_role_review": bool(labels.get("needs_role_review")),
        "source_index": int(clip.get("source_index", 0)),
        "motion_hint": labels.get("motion_hint"),
        "visual_reviewed": bool(visual),
        "duration": round(end - start, 3),
    }


def _section_for_role(profile: Mapping[str, Any], role: str) -> Optional[Mapping[str, Any]]:
    for section in profile.get("sections") or []:
        if isinstance(section, Mapping) and role in (section.get("roles") or []):
            return section
    return None


def _coverage(candidates: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> Dict[str, Any]:
    roles = {str(candidate.get("story_role")) for candidate in candidates}
    required_groups = [
        [str(role) for role in group]
        for group in (profile.get("required_groups") or [])
        if isinstance(group, (list, tuple)) and group
    ]
    missing: List[List[str]] = []
    present: List[List[str]] = []
    for normalized_group in required_groups:
        if roles.intersection(normalized_group):
            present.append(normalized_group)
        else:
            missing.append(normalized_group)
    return {
        "required_groups": required_groups,
        "present_groups": present,
        "missing_groups": missing,
        "present_roles": sorted(roles),
    }


def _section_sort_key(section: Mapping[str, Any], candidate: Mapping[str, Any]) -> Tuple[int, int, str]:
    role_order = {str(role): index for index, role in enumerate(section.get("roles") or [])}
    role = str(candidate.get("story_role") or "other")
    return (
        role_order.get(role, len(role_order)),
        int(candidate.get("source_index", 0)),
        str(candidate.get("candidate_id") or ""),
    )


def build_story_plan(
    analysis: Any,
    *,
    profile: Mapping[str, Any],
    title: Optional[str] = None,
    target_duration_s: Optional[float] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    normalized = normalize_analysis(analysis, base_dir=base_dir)
    project = normalized.get("project") or {}
    target = max(10.0, as_float(target_duration_s, as_float(project.get("target_duration_s"), 120.0)))
    candidates: List[Dict[str, Any]] = []
    for clip in normalized["clips"]:
        labels = clip.get("labels") or {}
        if labels.get("keep") is False or as_float(clip.get("duration")) <= 0:
            continue
        candidates.append(_make_candidate(clip))

    coverage = _coverage(candidates, profile)
    must_ids: set[str] = set()
    for group in profile.get("required_groups") or []:
        matching = [candidate for candidate in candidates if candidate["story_role"] in group]
        if matching:
            best = max(matching, key=lambda item: (item["quality"], item["confidence"], -item["source_index"]))
            must_ids.add(best["candidate_id"])

    chosen_by_section: Dict[str, List[Dict[str, Any]]] = {}
    selected_ids: set[str] = set()
    for section in profile.get("sections") or []:
        section_id = str(section.get("id"))
        roles = set(section.get("roles") or [])
        pool = [candidate for candidate in candidates if candidate["story_role"] in roles]
        required = [candidate for candidate in pool if candidate["candidate_id"] in must_ids]
        chosen: List[Dict[str, Any]] = sorted(required, key=lambda item: _section_sort_key(section, item))
        selected_ids.update(item["candidate_id"] for item in chosen)
        budget = max(3.0, target * as_float(section.get("weight"), 0.0))
        current = sum(item["duration"] for item in chosen)
        ranked = sorted(pool, key=lambda item: (-item["quality"], -item["confidence"], item["source_index"]))
        for candidate in ranked:
            if candidate["candidate_id"] in selected_ids or len(chosen) >= 7:
                continue
            if current >= budget and chosen:
                break
            chosen.append(candidate)
            selected_ids.add(candidate["candidate_id"])
            current += candidate["duration"]
        if chosen:
            chosen_by_section[section_id] = sorted(chosen, key=lambda item: _section_sort_key(section, item))

    estimated = sum(item["duration"] for items in chosen_by_section.values() for item in items)
    if estimated < target:
        extras = sorted(
            [candidate for candidate in candidates if candidate["candidate_id"] not in selected_ids],
            key=lambda item: (-item["quality"], -item["confidence"], item["source_index"]),
        )
        for candidate in extras:
            if estimated >= target:
                break
            section = _section_for_role(profile, candidate["story_role"])
            if not section:
                continue
            section_id = str(section.get("id"))
            bucket = chosen_by_section.setdefault(section_id, [])
            if len(bucket) >= 7:
                continue
            bucket.append(candidate)
            bucket.sort(key=lambda item: _section_sort_key(section, item))
            selected_ids.add(candidate["candidate_id"])
            estimated += candidate["duration"]

    structure: List[Dict[str, Any]] = []
    selected: List[Dict[str, Any]] = []
    for index, section in enumerate(profile.get("sections") or [], start=1):
        section_id = str(section.get("id"))
        clips = chosen_by_section.get(section_id) or []
        if not clips:
            continue
        selected.extend(clips)
        structure.append({
            "id": f"s{index:02d}",
            "act": int(section.get("act", 2)),
            "role": section_id,
            "section": str(section.get("title") or section_id),
            "description": f"按 {', '.join(str(role) for role in section.get('roles') or [])} 组织的叙事段落",
            "clips": [{key: value for key, value in clip.items() if key not in {"duration"}} for clip in clips],
        })

    total_duration = sum(as_float(clip.get("end")) - as_float(clip.get("start")) for clip in selected)
    category_duration: Dict[str, float] = {}
    for clip in selected:
        category = str(clip.get("content_class") or "other")
        category_duration[category] = category_duration.get(category, 0.0) + as_float(clip.get("duration"))
    ratios = {
        category: round(duration / total_duration, 3) if total_duration else 0.0
        for category, duration in category_duration.items()
    }

    warnings: List[str] = []
    if coverage["missing_groups"]:
        warnings.append("Missing coverage groups: " + "; ".join(" or ".join(group) for group in coverage["missing_groups"]))
    if any(not clip.get("visual_reviewed") for clip in selected):
        warnings.append("One or more selected clips have not been visually reviewed.")
    if any(clip.get("needs_role_review") for clip in selected):
        warnings.append("One or more selected clips have an ambiguous automatic story role and need human review.")
    average = total_duration / len(selected) if selected else 0.0
    if selected and not 2.5 <= average <= 5.5:
        warnings.append(f"Average selected shot duration is {average:.1f}s; 3-4s is only an advisory center.")
    if selected and total_duration > target + max(3.0, target * 0.10):
        warnings.append(
            f"Estimated duration {total_duration:.1f}s exceeds target {target:.1f}s; coverage is preserved and trimming requires review."
        )
    advisory = profile.get("content_ratio_advisory") or {}
    for category, bounds in advisory.items():
        if not (isinstance(bounds, list) and len(bounds) == 2):
            continue
        ratio = ratios.get(str(category), 0.0)
        if ratio < as_float(bounds[0]) or ratio > as_float(bounds[1]):
            warnings.append(f"{category} ratio {ratio:.0%} is outside advisory range {as_float(bounds[0]):.0%}-{as_float(bounds[1]):.0%}.")

    project_title = title or str(project.get("title") or "Travel Vlog")
    return {
        "schema_version": STORY_VERSION,
        "generated_at": utc_now(),
        "status": "needs_review",
        "title": project_title,
        "profile": str(profile.get("name") or project.get("profile") or "travel"),
        "target_duration_s": round(target, 3),
        "estimated_duration_s": round(total_duration, 3),
        "structure": structure,
        "highlights": [],
        "coverage": coverage,
        "content_ratios": ratios,
        "bgm_suggestion": str(profile.get("bgm_suggestion") or ""),
        "editing_notes": "保持完整行程或到店流程；高光片头未自动插入，需在人工复核后结构化添加。",
        "warnings": warnings,
        "approval": {"required": True, "approved": False},
        "summary": {
            "source_clips": len(normalized["clips"]),
            "candidate_clips": len(candidates),
            "selected_clips": len(selected),
            "sections": len(structure),
        },
    }


def analysis_index(analysis: Mapping[str, Any]) -> Tuple[Dict[str, Mapping[str, Any]], Dict[str, List[Mapping[str, Any]]]]:
    exact: Dict[str, Mapping[str, Any]] = {}
    by_name: Dict[str, List[Mapping[str, Any]]] = {}
    for clip in analysis.get("clips") or []:
        path = Path(str(clip.get("file") or "")).expanduser()
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            key = os.path.normcase(str(path))
        exact[key] = clip
        by_name.setdefault(path.name.lower(), []).append(clip)
    return exact, by_name


def resolve_analysis_clip(
    raw_file: str,
    exact: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, List[Mapping[str, Any]]],
    *,
    base_dir: Optional[Path] = None,
) -> Mapping[str, Any]:
    path = Path(raw_file).expanduser()
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    try:
        key = os.path.normcase(str(path.resolve()))
    except OSError:
        key = os.path.normcase(str(path))
    if key in exact:
        return exact[key]
    matches = by_name.get(path.name.lower()) or []
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ContractError(f"ambiguous source filename in plan: {raw_file}")
    raise ContractError(f"plan source is absent from analysis: {raw_file}")


def repair_speech_boundaries(start: float, end: float, clip: Mapping[str, Any]) -> Tuple[float, float, List[str], List[str]]:
    duration = as_float(clip.get("duration"), 0.0)
    start = clamp(start, 0.0, duration)
    end = clamp(end, 0.0, duration)
    transcript = (clip.get("audio") or {}).get("transcript") or []
    fixes: List[str] = []
    for segment in transcript:
        if not isinstance(segment, Mapping):
            continue
        seg_start = as_float(segment.get("start"))
        seg_end = as_float(segment.get("end"))
        if seg_start < start < seg_end:
            old = start
            start = max(0.0, seg_start - 0.1)
            fixes.append(f"start {old:.3f} -> {start:.3f} to preserve speech")
        if seg_start < end < seg_end:
            old = end
            end = min(duration, seg_end + 0.2)
            fixes.append(f"end {old:.3f} -> {end:.3f} to preserve speech")
    start = round(start, 1)
    end = round(end, 1)
    issues: List[str] = []
    if end <= start:
        issues.append("end must be greater than start")
    if start < 0 or end > duration + 1e-6:
        issues.append("interval falls outside source duration")
    for segment in transcript:
        if not isinstance(segment, Mapping):
            continue
        seg_start = as_float(segment.get("start"))
        seg_end = as_float(segment.get("end"))
        if seg_start < start < seg_end or seg_start < end < seg_end:
            issues.append(f"boundary still intersects speech segment {segment.get('id')}")
    return start, end, fixes, issues


def load_proxy_map(data: Any) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not data:
        return mapping
    items = data.get("items") if isinstance(data, Mapping) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, Mapping):
                continue
            source = item.get("source")
            proxy = item.get("proxy")
            if source and proxy and item.get("status") in {None, "ready", "reused"}:
                mapping[os.path.normcase(str(Path(str(source)).resolve()))] = str(Path(str(proxy)).resolve())
    elif isinstance(data, Mapping):
        for source, proxy in data.items():
            if isinstance(proxy, str):
                mapping[os.path.normcase(str(Path(str(source)).resolve()))] = str(Path(proxy).resolve())
    return mapping


def compile_story(
    analysis_data: Any,
    plan: Mapping[str, Any],
    *,
    project_dir: Path,
    proxy_map_data: Any = None,
    bgm: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    analysis = normalize_analysis(analysis_data, base_dir=base_dir)
    exact, by_name = analysis_index(analysis)
    proxy_map = load_proxy_map(proxy_map_data)
    work_dir = project_dir / "work"
    transcript_path = (work_dir / "compiled_transcript.json").resolve()
    errors: List[str] = []
    visual_warning = "One or more selected clips have not been visually reviewed."
    role_warning = "One or more selected clips have an ambiguous automatic story role and need human review."
    warnings: List[str] = [
        str(warning)
        for warning in (plan.get("warnings") or [])
        if str(warning) not in {visual_warning, role_warning}
    ]
    selected_plan_items = [
        clip
        for section in (plan.get("structure") or [])
        if isinstance(section, Mapping)
        for clip in (section.get("clips") or [])
        if isinstance(clip, Mapping)
    ]
    if any(clip.get("visual_reviewed") is not True for clip in selected_plan_items):
        warnings.append(visual_warning)
    if any(clip.get("needs_role_review") is True for clip in selected_plan_items):
        warnings.append(role_warning)
    fixes: List[Dict[str, Any]] = []
    transcript_segments: List[Dict[str, Any]] = []
    render_clips: List[Dict[str, Any]] = []
    timeline_sections: List[Dict[str, Any]] = []
    chapters: List[Dict[str, Any]] = []
    section_badges: List[Dict[str, Any]] = []
    focus_events: List[Dict[str, Any]] = []
    cursor = 0.0
    any_speech = False

    segment_id = 1
    for section_index, section in enumerate(plan.get("structure") or [], start=1):
        section_start = cursor
        timeline_clips: List[Dict[str, Any]] = []
        for clip_index, plan_clip in enumerate(section.get("clips") or [], start=1):
            raw_file = str(plan_clip.get("file") or "")
            try:
                source_clip = resolve_analysis_clip(raw_file, exact, by_name, base_dir=base_dir)
                source = Path(str(source_clip.get("file"))).resolve()
                if not source.is_file():
                    raise ContractError(f"source file not found: {source}")
                start = as_float(plan_clip.get("start"), -1.0)
                end = as_float(plan_clip.get("end"), -1.0)
                if start < 0 or end <= start:
                    raise ContractError(f"invalid interval {start}-{end}")
                repaired_start, repaired_end, clip_fixes, clip_issues = repair_speech_boundaries(start, end, source_clip)
                if clip_issues:
                    raise ContractError("; ".join(clip_issues))
                if clip_fixes:
                    fixes.append({
                        "section": section_index,
                        "clip": clip_index,
                        "file": str(source),
                        "changes": clip_fixes,
                    })
                source_key = os.path.normcase(str(source))
                proxy_value = proxy_map.get(source_key)
                if not proxy_value:
                    raise ContractError(f"normalized proxy is missing for selected source: {source}")
                render_source = Path(proxy_value).resolve()
                if not render_source.is_file():
                    raise ContractError(f"normalized proxy not found: {render_source}")
                text = str(plan_clip.get("subtitle") or "").strip()
                duration = round(repaired_end - repaired_start, 3)
                if duration <= 0:
                    raise ContractError("repaired interval has no duration")
                transcript_segments.append({
                    "id": segment_id,
                    "start": repaired_start,
                    "end": repaired_end,
                    "text": text,
                })
                render_clips.append({
                    "video": str(render_source),
                    "transcript": str(transcript_path),
                    "segment_id": segment_id,
                })
                timeline_clip = {
                    "id": f"s{section_index:02d}c{clip_index:02d}",
                    "source": str(source),
                    "render_source": str(render_source),
                    "source_in": repaired_start,
                    "source_out": repaired_end,
                    "timeline_in": round(cursor, 3),
                    "timeline_out": round(cursor + duration, 3),
                    "duration": duration,
                    "story_role": str(plan_clip.get("story_role") or "other"),
                    "content_class": str(plan_clip.get("content_class") or "other"),
                    "shot_type": str(plan_clip.get("shot_type") or ""),
                    "camera": str(plan_clip.get("camera") or ""),
                    "note": str(plan_clip.get("note") or ""),
                    "subtitle": text,
                    "segment_id": segment_id,
                }
                timeline_clips.append(timeline_clip)
                if text or bool((source_clip.get("audio") or {}).get("has_speech")):
                    any_speech = True
                motion_hint = plan_clip.get("motion_hint")
                camera = str(plan_clip.get("camera") or "").lower()
                unstable_camera_tokens = ("handheld", "shaky", "\u624b\u6301", "\u5267\u70c8", "\u6296\u52a8")
                if motion_hint == "subtle_push" and duration >= 3.5 and not any(token in camera for token in unstable_camera_tokens):
                    focus_events.append({
                        "start": round(cursor + 0.15, 3),
                        "end": round(cursor + duration - 0.15, 3),
                        "x": clamp(as_float(plan_clip.get("focus_x"), 0.5), 0.0, 1.0),
                        "y": clamp(as_float(plan_clip.get("focus_y"), 0.5), 0.0, 1.0),
                        "zoom": 1.08,
                        "transition": min(0.35, duration / 4),
                        "marker": False,
                    })
                cursor += duration
                segment_id += 1
            except (ContractError, OSError) as exc:
                errors.append(f"section {section_index} clip {clip_index}: {exc}")

        if timeline_clips:
            section_end = cursor
            section_title = str(section.get("section") or f"Section {section_index}")
            timeline_sections.append({
                "id": str(section.get("id") or f"s{section_index:02d}"),
                "act": int(section.get("act", 2)),
                "role": str(section.get("role") or ""),
                "title": section_title,
                "timeline_in": round(section_start, 3),
                "timeline_out": round(section_end, 3),
                "clips": timeline_clips,
            })
            chapters.append({"title": section_title, "start": round(section_start, 3), "end": round(section_end, 3)})
            section_badges.append({
                "text": section_title,
                "start": round(section_start, 3),
                "end": round(min(section_start + 3.0, section_end), 3),
                "fade_in": 220,
                "fade_out": 300,
                "source": "travel-vlog-pipeline:section",
            })

    if not render_clips:
        errors.append("story plan compiled to zero clips")
    if not proxy_map:
        errors.append("A ready normalized proxy map is required; source fallback is disabled.")
    coverage = copy.deepcopy(plan.get("coverage") or {})
    coverage["missing_groups"] = plan_missing_groups(plan)
    if coverage.get("missing_groups"):
        warnings.append("Story coverage gaps remain and require explicit user acceptance before full render.")

    transcript = {
        "source": "travel-vlog-pipeline",
        "language": "zh" if any_speech else "und",
        "segments": transcript_segments,
    }
    timeline = {
        "schema_version": TIMELINE_VERSION,
        "generated_at": utc_now(),
        "source_plan_sha256": None,
        "profile": str(plan.get("profile") or "travel"),
        "title": str(plan.get("title") or "Travel Vlog"),
        "duration": round(cursor, 3),
        "sections": timeline_sections,
        "coverage": copy.deepcopy(coverage),
    }
    render_config: Dict[str, Any] = {
        "version": "render_config.v1",
        "clips": render_clips,
        "title": str(plan.get("title") or "Travel Vlog"),
        "chapters": chapters,
        "cover_duration": 0.0,
        "subtitle_style": "minimal",
        "speech_denoise": "off",
        "versioned_output": True,
    }
    if section_badges:
        render_config["text_badges"] = section_badges
    if focus_events:
        render_config["focus_events"] = focus_events
    if bgm:
        bgm_path = Path(bgm).expanduser().resolve()
        if not bgm_path.is_file():
            errors.append(f"BGM file not found: {bgm_path}")
        else:
            render_config.update({
                "bgm": str(bgm_path),
                "bgm_volume": 0.12,
                "bgm_fade_out": 3.0,
                "bgm_ducking": bool(any_speech),
            })
    report = {
        "schema_version": COMPILE_VERSION,
        "generated_at": utc_now(),
        "status": "blocked" if errors else ("needs_review" if warnings else "ready"),
        "errors": errors,
        "warnings": list(dict.fromkeys(warnings)),
        "speech_boundary_fixes": fixes,
        "summary": {
            "clips": len(render_clips),
            "sections": len(timeline_sections),
            "duration": round(cursor, 3),
            "subtitled_clips": sum(1 for segment in transcript_segments if segment["text"]),
            "section_badges": len(section_badges),
            "focus_events": len(focus_events),
            "proxy_entries": len(proxy_map),
        },
    }
    return {
        "transcript": transcript,
        "timeline": timeline,
        "render_config": render_config,
        "report": report,
    }


def story_plan_sha256(path: os.PathLike[str] | str) -> str:
    return file_sha256(path)


def plan_missing_groups(plan: Mapping[str, Any]) -> List[List[str]]:
    coverage = plan.get("coverage") or {}
    required_groups = coverage.get("required_groups") or []
    if not required_groups:
        return [list(map(str, group)) for group in (coverage.get("missing_groups") or [])]
    selected_roles = {
        str(clip.get("story_role") or "other")
        for section in (plan.get("structure") or [])
        if isinstance(section, Mapping)
        for clip in (section.get("clips") or [])
        if isinstance(clip, Mapping)
    }
    return [
        [str(role) for role in group]
        for group in required_groups
        if not selected_roles.intersection(str(role) for role in group)
    ]


def _canonical_gap_set(groups: Sequence[Sequence[Any]]) -> set[Tuple[str, ...]]:
    return {
        tuple(sorted(str(role) for role in group))
        for group in groups
        if isinstance(group, (list, tuple)) and group
    }


def validate_story_approval(
    plan_path: Path,
    receipt_path: Path,
    *,
    expected_bundle_sha256: Optional[str] = None,
) -> Tuple[bool, str]:
    if not receipt_path.is_file():
        return False, "story approval receipt is missing"
    try:
        receipt = load_json(receipt_path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"story approval receipt is unreadable: {exc}"
    if receipt.get("schema_version") != "travel-vlog-story-approval/2":
        return False, "story approval receipt schema is missing or unsupported"
    if receipt.get("decision") != "approve":
        return False, "story approval decision is not approve"
    current = story_plan_sha256(plan_path)
    if receipt.get("plan_sha256") != current:
        return False, "story plan changed after approval"
    if expected_bundle_sha256 and receipt.get("integrity_bundle_sha256") != expected_bundle_sha256:
        return False, "compiled artifacts or reviewed media changed after approval"
    try:
        plan = load_json(plan_path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"story plan is unreadable: {exc}"
    missing = plan_missing_groups(plan)
    accepted = receipt.get("accepted_coverage_gaps") or []
    if _canonical_gap_set(missing) != _canonical_gap_set(accepted):
        return False, "accepted coverage gaps do not match the current story plan"
    return True, "approved"
