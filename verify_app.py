"""Offline acceptance checks for the source app and its frozen executable.

The launcher calls ``run_verification`` for its hidden ``--verify`` option.
Every fixture is created beneath the caller's dedicated report directory.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import uuid
import wave

from converter import ConversionCancelled, convert_file, ffmpeg_path
from gui import Application


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _pump_until_idle(root: tk.Tk, app: Application, deadline: float) -> None:
    """Exercise real scheduled Tk callbacks and the real background workers."""
    while app.mode != "idle":
        if time.monotonic() >= deadline:
            app.cancel_event.set()
            raise TimeoutError("GUI verification exceeded the 120-second deadline.")
        root.update()
        time.sleep(0.01)
    root.update()


def _layout_report(root: tk.Tk, app: Application) -> dict:
    """Check the main controls without showing an interactive test window."""
    root.update_idletasks()
    configured = root.geometry().split("+", 1)[0]
    requested = [root.winfo_reqwidth(), root.winfo_reqheight()]
    # A withdrawn toplevel can retain its initial 1x1 or 200x200 WM geometry.
    # Requested geometry still identifies overflow in the fixed UI content.
    width, height = (int(part) for part in configured.split("x"))
    if width <= 1 or height <= 1 or (width, height) == (200, 200):
        width, height = 1080, 760
    controls = {}
    for name in ("add_button", "folder_button", "output_entry", "start_button",
                 "cancel_button", "status_label", "tree"):
        widget = getattr(app, name)
        controls[name] = {
            "requested": [widget.winfo_reqwidth(), widget.winfo_reqheight()],
            "actual": [widget.winfo_width(), widget.winfo_height()],
            "managed_by": widget.winfo_manager(),
        }
        _assert(bool(widget.winfo_manager()), f"GUI control is unmanaged: {name}")
        _assert(widget.winfo_reqwidth() > 0 and widget.winfo_reqheight() > 0,
                f"GUI control has no requested area: {name}")
    overflow = requested[0] > width or requested[1] > height
    # Treeview has a flexible central row; its natural height may exceed the
    # window. Compare fixed controls and total requested width as useful checks.
    fixed_height = requested[1] - app.tree.winfo_reqheight()
    fixed_overflow = requested[0] > width or fixed_height >= height
    _assert(not fixed_overflow,
            f"Fixed GUI content does not fit {width}x{height}: requested={requested}")
    return {
        "configured_size": [width, height], "requested_size": requested,
        "requested_overflow_including_flexible_table": overflow,
        "fixed_content_height": fixed_height, "fixed_content_overflow": fixed_overflow,
        "controls": controls, "window_state": root.state(),
    }


def run_verification(input_mgg: Path, report_dir: Path) -> dict:
    """Run the mixed batch through the GUI, raising after saving a failed report."""
    started = time.monotonic()
    deadline = started + 120.0
    report_dir = Path(report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report: dict = {
        "passed": False, "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version, "executable": sys.executable,
        "report_path": str(report_path), "checks": {},
    }
    root = None
    app = None
    source = None
    source_hash = None
    callback_errors: list[str] = []
    try:
        source = Path(input_mgg).resolve(strict=True)
        _assert(source.is_file(), "Verification input must be a real MGG file.")
        source_hash = _sha256(source)
        report["original_input"] = {"path": str(source), "sha256_before": source_hash}
        ffmpeg = ffmpeg_path().resolve(strict=True)
        bundle_root = Path(sys._MEIPASS).resolve() if hasattr(sys, "_MEIPASS") else None
        in_bundle = bool(bundle_root and ffmpeg.is_relative_to(bundle_root))
        report["resources"] = {
            "ffmpeg": str(ffmpeg), "ffmpeg_size": ffmpeg.stat().st_size,
            "bundle_root": str(bundle_root) if bundle_root else None,
            "ffmpeg_in_bundle": in_bundle,
        }
        if report["frozen"]:
            _assert(in_bundle, "Frozen executable did not use its bundled FFmpeg.")

        fixture_root = report_dir / "fixtures" / ("中文 批量 (验收)-" + uuid.uuid4().hex[:8])
        fixture_root.mkdir(parents=True, exist_ok=False)
        output_dir = fixture_root / "output"
        output_dir.mkdir()
        # Two failures precede the two valid files in the sorted folder import.
        # This demonstrates that a bad input cannot stop the remaining queue.
        corrupt = fixture_root / "01 损坏 OGG (测试).ogg"
        corrupt.write_bytes(b"OggS" + b"invalid-ogg-page\x00" * 40)
        mgg = fixture_root / "02 中文 歌曲 (原始复制).mgg"
        shutil.copyfile(source, mgg)
        keyless = fixture_root / "03 外部密钥 (不支持).mgg"
        keyless.write_bytes(b"\x55" * 128 + b"musicex\x00")
        wav = fixture_root / "sentinel.wav"
        with wave.open(str(wav), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(22050)
            stream.writeframes(b"".join(
                struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * sample / 22050)))
                for sample in range(22050)
            ))
        sentinel = output_dir / "sentinel.mp3"
        sentinel_bytes = b"EXISTING OUTPUT MUST NEVER BE OVERWRITTEN\n"
        sentinel.write_bytes(sentinel_bytes)
        inputs = [corrupt, mgg, keyless, wav]
        hashes_before = {str(path): _sha256(path) for path in inputs}
        report["fixture_root"] = str(fixture_root)
        report["output_dir"] = str(output_dir)

        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda kind, value, tb: callback_errors.append(
            "".join(traceback.format_exception(kind, value, tb)))
        app = Application(root)
        report["tk"] = {"version": root.tk.call("info", "patchlevel"),
                        "scaling": root.tk.call("tk", "scaling")}
        app.output_dir.set(str(output_dir))
        app.output_is_custom = True
        report["geometry"] = _layout_report(root, app)
        app.add_paths([fixture_root])
        _pump_until_idle(root, app, deadline)
        queued_paths = {str(item["path"]) for item in app.items.values()}
        report["scan"] = {"queued_paths": sorted(queued_paths),
                          "status": app.status.get()}
        _assert(queued_paths == set(hashes_before),
                "Folder scanning omitted an input or included the output directory.")
        report["checks"]["recursive_scan_excludes_output"] = True
        # Adding the same files again must leave each source in the queue once.
        app.add_paths(inputs)
        _pump_until_idle(root, app, deadline)
        _assert(len(app.items) == len(inputs), "Repeated imports duplicated queue entries.")
        report["checks"]["duplicate_import_ignored"] = True

        app._start()
        _assert(app.mode == "converting", "The GUI did not start its conversion worker.")
        _pump_until_idle(root, app, deadline)
        rows = [{**item, "path": str(item["path"])} for item in app.items.values()]
        report["queue"] = rows
        report["summary"] = app.summary.get()
        report["status"] = app.status.get()
        successes = [item for item in rows if item["status"] == "成功"]
        failures = [item for item in rows if item["status"] == "失败"]
        _assert(len(successes) >= 2 and len(failures) >= 2,
                f"Expected at least 2 successes and 2 failures; got {len(successes)}/{len(failures)}.")
        _assert(len(successes) + len(failures) == len(inputs), "Some jobs never completed.")
        by_source = {item["path"]: item for item in rows}
        _assert(by_source[str(mgg)]["status"] == "成功", "Real MGG conversion failed.")
        _assert(by_source[str(wav)]["status"] == "成功", "WAV conversion failed.")
        _assert(by_source[str(corrupt)]["status"] == "失败", "Corrupt OGG was accepted.")
        _assert(by_source[str(keyless)]["status"] == "失败", "Keyless musicex was accepted.")
        _assert("外部密钥" in by_source[str(keyless)]["message"],
                "Unsupported musicex did not explain the external-key requirement.")
        _assert("失败" in by_source[str(corrupt)]["message"] and
                len(by_source[str(corrupt)]["message"]) >= 12,
                "Corrupt OGG did not produce a specific conversion error.")
        report["checks"]["mixed_batch_continues_after_failures"] = True
        report["checks"]["failure_reasons_are_specific"] = True

        _assert(sentinel.read_bytes() == sentinel_bytes, "Existing output was overwritten.")
        wav_output = Path(by_source[str(wav)]["output"])
        _assert(wav_output != sentinel and wav_output.is_file(),
                "The name collision did not create a separate MP3.")
        report["collision"] = {"preserved_file": str(sentinel),
                               "new_file": str(wav_output)}
        report["checks"]["existing_output_preserved"] = True

        decoded_reports = []
        for item in successes:
            target = Path(item["output"])
            remaining = deadline - time.monotonic()
            _assert(remaining > 0, "Verification deadline elapsed before decoding outputs.")
            result = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-nostdin", "-v", "info", "-xerror",
                 "-i", str(target), "-map", "0:a:0", "-f", "null", "-"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=min(30.0, remaining),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _assert(result.returncode == 0, f"Full MP3 decode failed: {result.stderr[-1800:]}")
            _assert("Input #0, mp3," in result.stderr and "Audio: mp3" in result.stderr,
                    f"Output was not recognized as MP3 audio: {target}")
            decoded_reports.append({"path": str(target), "size": target.stat().st_size,
                                    "sha256": _sha256(target), "full_decode": "passed",
                                    "ffmpeg_log": result.stderr[-3000:]})
        report["outputs"] = decoded_reports
        report["checks"]["all_successful_mp3s_fully_decodable"] = True
        created_mp3s = set(output_dir.glob("*.mp3")) - {sentinel}
        _assert(created_mp3s == {Path(item["output"]) for item in successes},
                "Failed inputs left an unexpected output file.")
        report["checks"]["failed_inputs_leave_no_output"] = True

        cancel_event = threading.Event()
        cancel_event.set()
        cancelled_output = fixture_root / "cancelled-output"
        try:
            convert_file(mgg, cancelled_output, cancel_event=cancel_event)
        except ConversionCancelled:
            pass
        else:
            raise AssertionError("A pre-cancelled conversion did not raise ConversionCancelled.")
        _assert(not cancelled_output.exists(), "A cancelled job created its output directory.")
        report["checks"]["pre_cancelled_conversion_has_no_output"] = True

        hashes_after = {str(path): _sha256(path) for path in inputs}
        report["fixture_hashes"] = {"before": hashes_before, "after": hashes_after}
        _assert(hashes_before == hashes_after, "Conversion modified an input fixture.")
        original_after = _sha256(source)
        report["original_input"]["sha256_after"] = original_after
        _assert(original_after == source_hash, "Verification modified the original MGG.")
        report["checks"]["all_input_hashes_unchanged"] = True
        _assert(not callback_errors, "Tk callback raised: " + "\n".join(callback_errors))
        report["checks"]["no_tk_callback_errors"] = True
        report["passed"] = True
        return report
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        if app is not None and app.mode != "idle":
            app.cancel_event.set()
            worker = app.worker
            if worker is not None:
                worker.join(timeout=3)
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        if source is not None and source_hash is not None:
            try:
                report["original_input"]["sha256_after"] = _sha256(source)
            except OSError as error:
                report["original_input"]["hash_after_error"] = str(error)
        report["tk_callback_errors"] = callback_errors
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
