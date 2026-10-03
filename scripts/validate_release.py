from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "travel-vlog-pipeline"


def fail(message: str) -> None:
    raise SystemExit(f"release validation failed: {message}")


def main() -> int:
    skill_md = SKILL / "SKILL.md"
    if not skill_md.is_file():
        fail(f"missing {skill_md.relative_to(ROOT)}")

    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter")
    try:
        _, frontmatter, _ = text.split("---", 2)
    except ValueError:
        fail("SKILL.md frontmatter is not closed")

    metadata = yaml.safe_load(frontmatter) or {}
    if set(metadata) != {"name", "description"}:
        fail("SKILL.md frontmatter must contain only name and description")
    if metadata["name"] != "travel-vlog-pipeline":
        fail("skill name must match its folder")
    if not isinstance(metadata["description"], str) or len(metadata["description"].strip()) < 80:
        fail("skill description is too short to trigger reliably")

    forbidden_names = {".vendor", ".venv", ".tools", "__pycache__"}
    forbidden_suffixes = {".pyc", ".pyo", ".mp4", ".mov", ".mkv", ".avi"}
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == ".git" or relative.parts[0].startswith((".release-venv", ".tmp-")):
            continue
        if any(part in forbidden_names for part in relative.parts):
            fail(f"forbidden runtime path is present: {relative}")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes:
            fail(f"forbidden generated/binary file is present: {relative}")

    required = [
        SKILL / "agents" / "openai.yaml",
        SKILL / "scripts" / "run_pipeline.ps1",
        SKILL / "scripts" / "runtime_integrity.py",
        SKILL / "assets" / "upstream-lock.json",
        SKILL / "references" / "artifact-contract.md",
        SKILL / "references" / "editing-preferences.md",
        SKILL / "references" / "jianying-native-draft.md",
        SKILL / "references" / "jianying-local-adapter.md",
        SKILL / "references" / "render-workflow.md",
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "LICENSE",
        ROOT / "NOTICE",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail(f"missing required files: {', '.join(missing)}")

    print("release validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
