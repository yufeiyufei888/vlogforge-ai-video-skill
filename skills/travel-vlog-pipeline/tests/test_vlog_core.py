from __future__ import annotations

import json
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from vlog_core import (  # noqa: E402
    build_story_plan,
    classify_analysis,
    compile_story,
    load_profile,
    validate_story_approval,
    write_json,
)
import pipeline as pipeline_module  # noqa: E402
import runtime_integrity as runtime_integrity_module  # noqa: E402
from pipeline import cmd_compile, proxy_filter, resolve_project_path  # noqa: E402
from runtime_integrity import directory_tree_record, verify_vendor_lock  # noqa: E402


class VlogCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_proxy_filter_converts_to_limited_range_yuv420p(self) -> None:
        contain = proxy_filter(1920, 1080, 30.0, "contain")
        crop = proxy_filter(1920, 1080, 30.0, "crop")
        for value in (contain, crop):
            self.assertIn("out_range=tv", value)
            self.assertIn("format=yuv420p", value)

    def make_clip(self, name: str, role: str, description: str, *, speech: bool = False, source_index: int = 0) -> dict:
        path = self.root / name
        path.write_bytes(b"placeholder")
        transcript = [{"id": 1, "start": 1.0, "end": 3.0, "text": "这段话不能截断"}] if speech else []
        return {
            "file": str(path),
            "duration": 8.0,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "source_index": source_index,
            "visual": [{"time": 3.0, "description": description, "shot_type": "近景", "camera": "固定", "mood": "自然"}],
            "audio": {"has_track": True, "has_speech": speech, "transcript": transcript},
            "preprocessing": {"recommended_range": [0.5, 7.5], "skip_zones": []},
            "labels": {"story_role": role, "content_class": "unclassified", "quality": 0.8, "keep": True, "human_override": True},
        }

    def food_analysis(self) -> dict:
        specs = [
            ("01-arrival.mp4", "arrival", "arrive near the restaurant"),
            ("02-exterior.mp4", "exterior", "storefront and sign"),
            ("03-entry.mp4", "entry", "enter through the door"),
            ("04-room.mp4", "environment", "interior and seating"),
            ("05-order.mp4", "ordering", "read menu and order"),
            ("06-serving.mp4", "serving", "dish arrives at the table"),
            ("07-food.mp4", "food_hero", "detailed food closeup"),
            ("08-action.mp4", "food_action", "cut and lift the food"),
            ("09-taste.mp4", "tasting_reaction", "honest tasting reaction"),
            ("10-exit.mp4", "summary_exit", "summary and leave"),
        ]
        return {
            "project": {"title": "测试探店", "profile": "food", "target_duration_s": 40},
            "clips": [
                self.make_clip(name, role, description, speech=role == "arrival", source_index=index)
                for index, (name, role, description) in enumerate(specs)
            ],
        }

    def test_classification_preserves_human_override(self) -> None:
        data = self.food_analysis()
        classified = classify_analysis(data, profile="food")
        roles = [clip["labels"]["story_role"] for clip in classified["clips"]]
        self.assertEqual(roles[0], "arrival")
        self.assertEqual(roles[-1], "summary_exit")
        food_clip = next(clip for clip in classified["clips"] if clip["labels"]["story_role"] == "food_hero")
        self.assertEqual(food_clip["labels"]["content_class"], "food")

    def test_vendor_tree_drift_is_rejected(self) -> None:
        vendor = self.root / ".vendor" / "sample"
        vendor.mkdir(parents=True)
        script = vendor / "runner.py"
        script.write_text("print('pinned')\n", encoding="utf-8")
        record = directory_tree_record(vendor)
        lock = self.root / "upstream-lock.json"
        lock.write_text(
            json.dumps(
                {
                    "schema_version": "travel-vlog-upstream-lock/2",
                    "sources": [
                        {
                            "name": "sample",
                            "local_path": ".vendor/sample",
                            "tree_sha256": record["sha256"],
                            "tree_file_count": record["file_count"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        _, initial_errors = verify_vendor_lock(self.root, lock)
        self.assertEqual(initial_errors, [])
        with mock.patch.object(
            runtime_integrity_module,
            "is_reparse_path",
            side_effect=lambda path: Path(path) == vendor,
        ):
            _, source_root_errors = verify_vendor_lock(self.root, lock)
        self.assertTrue(any("vendor source path traverses" in error for error in source_root_errors))
        with mock.patch.object(
            runtime_integrity_module,
            "is_reparse_path",
            side_effect=lambda path: Path(path) == self.root / ".vendor",
        ):
            _, vendor_root_errors = verify_vendor_lock(self.root, lock)
        self.assertTrue(any("vendor root path traverses" in error for error in vendor_root_errors))
        with mock.patch.object(runtime_integrity_module, "reparse_paths", return_value=[vendor / "linked-package"]):
            _, reparse_errors = verify_vendor_lock(self.root, lock)
        self.assertTrue(any("reparse point" in error for error in reparse_errors))
        script.write_text("print('changed')\n", encoding="utf-8")
        _, changed_errors = verify_vendor_lock(self.root, lock)
        self.assertIn("vendor tree hash mismatch: sample", changed_errors)
        cache = vendor / "__pycache__"
        cache.mkdir()
        (cache / "runner.cpython-312.pyc").write_bytes(b"executable-cache")
        _, cache_errors = verify_vendor_lock(self.root, lock)
        self.assertTrue(any("forbidden Python bytecode cache" in error for error in cache_errors))

    def test_broken_reparse_project_path_is_rejected(self) -> None:
        candidate = self.root / "broken-project-link"
        with (
            mock.patch.object(pipeline_module.os.path, "lexists", side_effect=lambda path: Path(path) == candidate),
            mock.patch.object(pipeline_module, "is_reparse_path", return_value=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "symlink or junction"):
                resolve_project_path(candidate)

    def test_ambiguous_multi_stage_clip_requires_role_review(self) -> None:
        clip = self.make_clip("mixed.mp4", "other", "serving arrives dish food closeup taste reaction")
        clip["labels"] = {"content_class": "unclassified"}
        classified = classify_analysis({"project": {}, "clips": [clip]}, profile="food")
        self.assertTrue(classified["clips"][0]["labels"]["needs_role_review"])

    def test_story_plan_keeps_arrival_to_exit(self) -> None:
        classified = classify_analysis(self.food_analysis(), profile="food")
        profile = load_profile(Path(__file__).resolve().parents[1] / "assets" / "food-profile.json")
        plan = build_story_plan(classified, profile=profile, target_duration_s=40)
        selected_roles = [clip["story_role"] for section in plan["structure"] for clip in section["clips"]]
        self.assertEqual(selected_roles[0], "arrival")
        self.assertEqual(selected_roles[-1], "summary_exit")
        self.assertEqual(plan["coverage"]["missing_groups"], [])
        self.assertEqual(plan["status"], "needs_review")

    def test_story_plan_uses_role_order_when_source_indexes_are_reversed(self) -> None:
        data = self.food_analysis()
        data["clips"] = list(reversed(data["clips"]))
        for index, clip in enumerate(data["clips"]):
            clip["source_index"] = index
        classified = classify_analysis(data, profile="food")
        profile = load_profile(Path(__file__).resolve().parents[1] / "assets" / "food-profile.json")
        plan = build_story_plan(classified, profile=profile, target_duration_s=100)
        selected_roles = [clip["story_role"] for section in plan["structure"] for clip in section["clips"]]
        self.assertEqual(
            selected_roles,
            ["arrival", "exterior", "entry", "environment", "ordering", "serving", "food_hero", "food_action", "tasting_reaction", "summary_exit"],
        )

    def test_food_hero_does_not_hide_ordering_or_serving_gap(self) -> None:
        data = self.food_analysis()
        keep_roles = {"arrival", "entry", "environment", "food_hero", "tasting_reaction", "summary_exit"}
        data["clips"] = [clip for clip in data["clips"] if clip["labels"]["story_role"] in keep_roles]
        classified = classify_analysis(data, profile="food")
        profile = load_profile(Path(__file__).resolve().parents[1] / "assets" / "food-profile.json")
        plan = build_story_plan(classified, profile=profile, target_duration_s=40)
        self.assertIn(["ordering", "serving"], plan["coverage"]["missing_groups"])

    def test_target_overshoot_is_an_advisory_warning(self) -> None:
        classified = classify_analysis(self.food_analysis(), profile="food")
        profile = load_profile(Path(__file__).resolve().parents[1] / "assets" / "food-profile.json")
        plan = build_story_plan(classified, profile=profile, target_duration_s=20)
        self.assertGreater(plan["estimated_duration_s"], plan["target_duration_s"])
        self.assertTrue(any("exceeds target" in warning for warning in plan["warnings"]))

    def test_compile_repairs_speech_and_emits_renderer_contract(self) -> None:
        classified = classify_analysis(self.food_analysis(), profile="food")
        source = Path(classified["clips"][0]["file"])
        proxy = self.root / "arrival-proxy.mp4"
        proxy.write_bytes(b"proxy")
        plan = {
            "title": "测试探店",
            "profile": "food",
            "structure": [{
                "id": "s01",
                "act": 1,
                "role": "opening",
                "section": "抵达 — 开场",
                "clips": [{
                    "file": str(source),
                    "start": 1.5,
                    "end": 2.5,
                    "subtitle": "这段话不能截断",
                    "note": "到店",
                    "story_role": "arrival",
                    "content_class": "daily_transit",
                }],
            }],
            "coverage": {"missing_groups": []},
            "warnings": [],
        }
        project = self.root / "project"
        (project / "work").mkdir(parents=True)
        compiled = compile_story(
            classified,
            plan,
            project_dir=project,
            proxy_map_data={"items": [{"source": str(source), "proxy": str(proxy), "status": "ready"}]},
        )
        segment = compiled["transcript"]["segments"][0]
        render_clip = compiled["render_config"]["clips"][0]
        self.assertEqual(segment["start"], 0.9)
        self.assertEqual(segment["end"], 3.2)
        self.assertIsInstance(render_clip["segment_id"], int)
        self.assertEqual(Path(render_clip["video"]), proxy.resolve())
        self.assertEqual(compiled["render_config"]["text_badges"][0]["start"], 0.0)
        self.assertEqual(compiled["render_config"]["text_badges"][0]["end"], 2.3)
        self.assertEqual(compiled["report"]["summary"]["section_badges"], 1)
        self.assertEqual(compiled["report"]["errors"], [])

    def test_approval_is_bound_to_plan_hash(self) -> None:
        plan_path = self.root / "story_plan.json"
        receipt_path = self.root / "story_approval.json"
        write_json(plan_path, {"title": "A", "structure": [], "coverage": {"required_groups": [], "missing_groups": []}})
        from vlog_core import story_plan_sha256

        write_json(receipt_path, {
            "schema_version": "travel-vlog-story-approval/2",
            "decision": "approve",
            "plan_sha256": story_plan_sha256(plan_path),
            "integrity_bundle_sha256": "bundle-a",
            "accepted_coverage_gaps": [],
        })
        self.assertTrue(validate_story_approval(plan_path, receipt_path, expected_bundle_sha256="bundle-a")[0])
        valid, reason = validate_story_approval(plan_path, receipt_path, expected_bundle_sha256="bundle-b")
        self.assertFalse(valid)
        self.assertIn("changed", reason)
        write_json(plan_path, {"title": "B", "structure": []})
        valid, reason = validate_story_approval(plan_path, receipt_path)
        self.assertFalse(valid)
        self.assertIn("changed", reason)

    def test_approval_requires_exact_current_coverage_gaps(self) -> None:
        plan_path = self.root / "story_plan.json"
        receipt_path = self.root / "story_approval.json"
        plan = {
            "title": "A",
            "structure": [{"clips": [{"story_role": "arrival"}]}],
            "coverage": {"required_groups": [["arrival"], ["entry"]], "missing_groups": [["entry"]]},
        }
        write_json(plan_path, plan)
        from vlog_core import story_plan_sha256

        receipt = {
            "schema_version": "travel-vlog-story-approval/2",
            "decision": "approve",
            "plan_sha256": story_plan_sha256(plan_path),
            "accepted_coverage_gaps": [],
        }
        write_json(receipt_path, receipt)
        valid, reason = validate_story_approval(plan_path, receipt_path)
        self.assertFalse(valid)
        self.assertIn("coverage gaps", reason)
        receipt["accepted_coverage_gaps"] = [["entry"]]
        write_json(receipt_path, receipt)
        self.assertTrue(validate_story_approval(plan_path, receipt_path)[0])

    def test_compile_blocks_when_selected_source_has_no_proxy(self) -> None:
        classified = classify_analysis(self.food_analysis(), profile="food")
        source = Path(classified["clips"][0]["file"])
        plan = {
            "title": "Proxy gate",
            "profile": "food",
            "structure": [{
                "section": "Arrival",
                "clips": [{"file": str(source), "start": 0.0, "end": 2.0, "story_role": "arrival"}],
            }],
            "coverage": {"missing_groups": []},
            "warnings": [],
        }
        project = self.root / "project-no-proxy"
        (project / "work").mkdir(parents=True)
        compiled = compile_story(classified, plan, project_dir=project, proxy_map_data={"items": []})
        self.assertEqual(compiled["render_config"]["clips"], [])
        self.assertTrue(any("proxy" in error.lower() for error in compiled["report"]["errors"]))
        self.assertEqual(compiled["report"]["status"], "blocked")

    def test_blocked_compile_does_not_replace_last_good_render_config(self) -> None:
        analysis = classify_analysis(self.food_analysis(), profile="food")
        source = Path(analysis["clips"][0]["file"])
        plan = {
            "title": "Blocked publication",
            "profile": "food",
            "structure": [{"section": "Arrival", "clips": [{
                "file": str(source), "start": 0.0, "end": 2.0, "story_role": "arrival",
                "visual_reviewed": True, "needs_role_review": False,
            }]}],
            "coverage": {"missing_groups": []},
            "warnings": [],
        }
        project = self.root / "publish-gate"
        work = project / "work"
        work.mkdir(parents=True)
        analysis_path = work / "clip_analysis.json"
        plan_path = work / "story_plan.json"
        proxy_path = work / "proxy_map.json"
        config_path = work / "render_config.json"
        write_json(analysis_path, analysis)
        write_json(plan_path, plan)
        write_json(proxy_path, {"schema_version": "travel-vlog-proxy-map/1", "status": "blocked", "items": [], "errors": ["missing"]})
        write_json(config_path, {"marker": "last-good"})
        code = cmd_compile(argparse.Namespace(
            project=str(project), analysis=str(analysis_path), plan=str(plan_path), proxy_map=str(proxy_path), bgm=None,
        ))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["marker"], "last-good")
        report = json.loads((work / "compile_report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["published"])


if __name__ == "__main__":
    unittest.main()
