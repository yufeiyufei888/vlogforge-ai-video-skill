# Windows Runtime

## Project-Local Layout

Use the workspace's Python 3.12+ interpreter to create `<workspace>/.venv`. Install FFmpeg under `<workspace>/.tools/ffmpeg`; do not require WSL.

Core Python packages:

- `Pillow`: MaxAzure cover/title module import and image utilities.
- `PyYAML`: MaxAzure profile files.

Optional ASR package:

- `faster-whisper`: local Windows/CPU or NVIDIA transcription. Model weights download on first use.

`prepare` does not automatically select new clips for ASR. After reviewing frames, set `labels.needs_transcript: true` for the clips that need speech analysis. Use `transcribe --all` only when every audio-bearing clip should be processed explicitly.

Run `scripts/setup_runtime.ps1` from this skill to reproduce the environment. It downloads the pinned FFmpeg 8.1.1 Essentials 7z from the GyanD release channel linked by ffmpeg.org, verifies SHA-256 `23ad8969fbe701d44e6e7e2b97c5fae4a71224fc33a2560a9034e5110d029d15`, and extracts it locally with Windows `tar.exe`.

On a machine whose normal PowerShell policy blocks local scripts, run it with a process-scoped bypass; this does not change the user or system policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<skill>/scripts/setup_runtime.ps1" -Workspace "<workspace>" -WithAsr
```

The ASR install uses `assets/requirements-windows-py312.lock.txt`, and the setup report records interpreter, package-lock, the exact installed Python distribution/version set, the integrity-verifier hash, FFmpeg, and FFprobe hashes under `<workspace>/.tools/travel-vlog-runtime.json`.

Integrity preflight requires runtime schema `travel-vlog-runtime/2`. Run every pipeline command with the exact project-local Python recorded in that manifest; the selected FFmpeg and FFprobe must also be the recorded files. The runtime manifest is bound to the current package lock, installed distribution/version inventory, integrity verifier, upstream lock, named script snapshot, and complete vendor-tree records. Changing any of these makes the runtime fail closed and invalidates an existing approval.

Vendor Python bytecode caches and reparse points are rejected during setup and every later vendor gate; subprocesses run with bytecode writes disabled. Edit projects must use real directories: the pipeline rejects symlinks, junctions, linked files, and other reparse points anywhere in the project tree.

Run operational commands only through `scripts/run_pipeline.ps1`. Before Python starts, it rejects `__pycache__`, `.pyc`, `.pyo`, and reparse points anywhere in the local skill; clears inherited `PYTHONPATH`, `PYTHONHOME`, and startup hooks; then source-bootstraps the approved workspace interpreter with isolated `-I -S -B`. Child Python processes also ignore inherited Python path/home settings. Direct `pipeline.py` execution is intentionally rejected.

## Discovery Order

`pipeline.py` searches:

1. `TRAVEL_VLOG_FFMPEG_BIN`
2. `<workspace>/.tools/ffmpeg/bin`
3. a nested `ffmpeg-*-essentials_build/bin`
4. the current `PATH`

It never changes the user's permanent PATH.

The renderer defaults to deterministic `libx264`. Use `--encoder auto` only after a real NVENC/QSV/AMF smoke test succeeds. Local ASR defaults to `--device cpu --compute-type int8`; CUDA is opt-in because an NVIDIA display driver alone does not prove the required CUDA libraries are available.

## WSL

WSL is optional. This integration uses argument-array subprocess calls and Windows-safe paths, so WSL is not needed for normal operation.

## Privacy

FFmpeg and faster-whisper run locally. The first ASR run downloads model files from the configured model host. Do not configure a third-party vision endpoint without user consent.
