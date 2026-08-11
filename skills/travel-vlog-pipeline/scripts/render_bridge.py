#!/usr/bin/env python3
"""Run pinned MaxAzure render_final with an explicit encoder policy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vlog_core import write_json


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--vendor-scripts", required=True)
    parser.add_argument("--encoder", choices=["libx264", "auto"], default="libx264")
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--nonce", required=True)
    bridge_args, renderer_args = parser.parse_known_args()

    scripts = Path(bridge_args.vendor_scripts).expanduser().resolve()
    renderer = scripts / "render_final.py"
    if not renderer.is_file():
        print(f"Error: MaxAzure renderer not found: {renderer}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(scripts))
    import render_final  # type: ignore

    requested_output: Path | None = None
    for index, value in enumerate(renderer_args[:-1]):
        if value == "--output":
            requested_output = Path(renderer_args[index + 1]).expanduser().resolve()
            break
    selected_output: Path | None = None
    selected_output_preexisting = False
    requested_output_preexisting = bool(requested_output and requested_output.is_file())
    original_next_versioned_output_path = render_final.next_versioned_output_path

    def captured_next_versioned_output_path(path):
        nonlocal selected_output, selected_output_preexisting
        selected_output = Path(original_next_versioned_output_path(path)).resolve()
        selected_output_preexisting = selected_output.is_file()
        return str(selected_output)

    render_final.next_versioned_output_path = captured_next_versioned_output_path

    if bridge_args.encoder == "libx264":
        render_final.get_ffmpeg_encode_args = lambda gpu_info=None: [
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]

    original_audio_filters = render_final.build_speech_audio_filters

    def fixed_audio_filters(*, denoise, speed, loudness_enabled, cover_duration):
        filters = list(original_audio_filters(
            denoise=denoise,
            speed=speed,
            loudness_enabled=loudness_enabled,
            cover_duration=cover_duration,
        ))
        filters.extend([
            "aresample=48000",
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo",
        ])
        return filters

    render_final.build_speech_audio_filters = fixed_audio_filters

    original_argv = sys.argv
    return_code = 2
    failure: str | None = None
    try:
        try:
            sys.argv = [str(renderer), *renderer_args]
            result = render_final.main()
            return_code = int(result or 0)
        except SystemExit as exc:
            reported_code = int(exc.code or 0) if isinstance(exc.code, int) else 2
            return_code = reported_code if reported_code != 0 else 2
            failure = f"renderer raised SystemExit({exc.code!r})"
        except Exception as exc:
            return_code = 2
            failure = f"renderer raised {type(exc).__name__}: {exc}"
    finally:
        sys.argv = original_argv
        render_final.next_versioned_output_path = original_next_versioned_output_path
    actual_output = selected_output or requested_output
    actual_output_preexisting = selected_output_preexisting if selected_output else requested_output_preexisting
    receipt = {
        "schema_version": "travel-vlog-render-bridge/1",
        "nonce": bridge_args.nonce,
        "returncode": return_code,
        "requested_output": str(requested_output) if requested_output else None,
        "actual_output": str(actual_output) if actual_output else None,
        "preexisting": actual_output_preexisting,
        "exists": bool(actual_output and actual_output.is_file()),
        "failure": failure,
    }
    write_json(Path(bridge_args.result_json).expanduser().resolve(), receipt)
    if failure:
        print(f"Error: {failure}", file=sys.stderr)
    if return_code == 0 and not receipt["exists"]:
        print("Error: renderer returned success without the exact attributed output.", file=sys.stderr)
        return 2
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
