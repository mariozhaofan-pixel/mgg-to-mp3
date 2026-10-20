"""Offline acceptance checks, shared by source and frozen --self-test runs.

Fixtures are synthesized from a two-second tone, never from user music.
The container writer is independent of ncm_core and hard-codes format constants.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import uuid
import zlib

from Crypto.Cipher import AES

from converter import ConversionCancelled, _prepare_audio, convert_file, ffmpeg_path
from gui import Application
from ncm_core import extract_ncm


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _padded_encryption(key: bytes, plain: bytes) -> bytes:
    count = 16 - len(plain) % 16
    return AES.new(key, AES.MODE_ECB).encrypt(plain + bytes([count]) * count)


def _fixture_stream(key: bytes, plain: bytes) -> bytes:
    """Independent KSA and indexed stream; no production decoder helpers."""
    permutation = list(range(256))
    last = 0
    for index in range(256):
        last = (last + permutation[index] + key[index % len(key)]) % 256
        permutation[index], permutation[last] = permutation[last], permutation[index]
    result = bytearray(plain)
    for index in range(len(result)):
        position = (index + 1) % 256
        first = permutation[position]
        second = permutation[(position + first) % 256]
        result[index] ^= permutation[(first + second) % 256]
    return bytes(result)


def _ncm_fixture(
    audio: bytes, metadata: dict | None, *, cover: bytes = b"",
    cover_padding: int = 0, corrupt_metadata: bool = False,
    dj: bool = False, empty_key: bool = False,
) -> bytes:
    # Public container constants deliberately not imported from ncm_core.
    core_key = bytes.fromhex("687A4852416D736F356B496E62617857")
    meta_key = bytes.fromhex("2331346C6A6B5F215C5D2630553C2728")
    song_key = b"acceptance-fixture-only-20261020-9ce47d06"
    key_plain = b"neteasecloudmusic" + (b"" if empty_key else song_key)
    key_block = bytes(byte ^ 0x64 for byte in _padded_encryption(core_key, key_plain))
    if corrupt_metadata:
        meta_block = b"\x12invalid-optional-metadata\xfe"
    elif metadata is None:
        meta_block = b""
    else:
        payload = {"mainMusic": metadata, "programName": "离线节目"} if dj else metadata
        plain = (b"dj:" if dj else b"music:") + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = b"163 key(Don't modify):" + base64.b64encode(
            _padded_encryption(meta_key, plain))
        meta_block = bytes(byte ^ 0x63 for byte in encoded)
    frame_length = len(cover) + cover_padding
    return (
        b"CTENFDAM\x01\x70"
        + struct.pack("<I", len(key_block)) + key_block
        + struct.pack("<I", len(meta_block)) + meta_block
        + b"\0\0\0\0\x01"
        + struct.pack("<II", frame_length, len(cover))
        + cover + b"\x55" * cover_padding
        + _fixture_stream(song_key, audio)
    )


def _tiny_png() -> bytes:
    """An actual 8x8 RGB PNG, including independent CRCs and compressed pixels."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    scanlines = b"".join(b"\0" + bytes([40, 120, 220]) * 8 for _ in range(8))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def _tea_encrypt_block(block: bytes, key: bytes) -> bytes:
    """Independent 16-round TEA encryption for synthetic QMC key envelopes."""
    left, right = struct.unpack(">II", block)
    words = struct.unpack(">4I", key)
    total = 0
    mask = 0xFFFFFFFF
    for _ in range(16):
        total = (total + 0x9E3779B9) & mask
        left = (left + (((right << 4) + words[0])
                        ^ (right + total) ^ ((right >> 5) + words[1]))) & mask
        right = (right + (((left << 4) + words[2])
                          ^ (left + total) ^ ((left >> 5) + words[3]))) & mask
    return struct.pack(">II", left, right)


def _tencent_tea_encrypt(plain: bytes, key: bytes) -> bytes:
    padding = (-len(plain) - 10) % 8
    padded = bytes([0xA0 | padding]) + b"\x5a" * padding + b"\x71\x39" + plain + b"\0" * 7
    previous_cipher = previous_mixed = bytes(8)
    encrypted = bytearray()
    for start in range(0, len(padded), 8):
        mixed = bytes(a ^ b for a, b in zip(padded[start:start + 8], previous_cipher))
        block = _tea_encrypt_block(mixed, key)
        cipher = bytes(a ^ b for a, b in zip(block, previous_mixed))
        encrypted.extend(cipher)
        previous_cipher, previous_mixed = cipher, mixed
    return bytes(encrypted)


def _mgg_fixture(audio: bytes, *, footer: str, encv2: bool) -> bytes:
    """Short-key Map QMC2 fixture; does not call any production crypto code."""
    song_key = b"QMCtest!" + bytes((index * 29 + 7) % 256 for index in range(120))
    salt_key = bytes.fromhex("695646382b20150b")
    envelope_key = bytes(value for pair in zip(salt_key, song_key[:8]) for value in pair)
    ekey = base64.b64encode(
        song_key[:8] + _tencent_tea_encrypt(song_key[8:], envelope_key))
    if encv2:
        inner = _tencent_tea_encrypt(ekey, b"**#!(#$%&^a1cZ,T")
        outer = _tencent_tea_encrypt(inner, b"386ZJY!@#*$%^&)(")
        ekey = base64.b64encode(b"QQMusic EncV2,Key:" + outer)
    encrypted = bytearray(audio)
    for offset in range(len(encrypted)):
        position = offset if offset <= 0x7FFF else offset % 0x7FFF
        index = (position * position + 71214) % len(song_key)
        shift = (index + 4) % 8
        # QMC Map historically shifts both directions by the same count.
        stream_byte = ((song_key[index] << shift) | (song_key[index] >> shift)) & 255
        encrypted[offset] ^= stream_byte
    if footer == "V1":
        tail = ekey + b"\0"
        return bytes(encrypted) + tail + struct.pack("<I", len(tail))
    if footer == "QTag":
        tail = ekey + b",123456,2"
        return bytes(encrypted) + tail + struct.pack(">I", len(tail)) + b"QTag"
    raise ValueError("Unknown synthetic QMC footer.")


def _run_ffmpeg(executable: Path, args: list[str], deadline: float) -> tuple[str, str]:
    remaining = deadline - time.monotonic()
    _assert(remaining > 0, "Verification exceeded its deadline.")
    process = subprocess.run(
        [str(executable), "-hide_banner", "-nostdin", *args],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace", timeout=min(45.0, remaining),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    _assert(process.returncode == 0,
            f"FFmpeg exited {process.returncode}: {process.stderr[-2400:]}")
    return process.stdout, process.stderr


def _pump_until_idle(root: tk.Tk, app: Application, deadline: float) -> None:
    while app.mode != "idle":
        if time.monotonic() >= deadline:
            app.cancel_event.set()
            raise TimeoutError("GUI worker did not become idle before the deadline.")
        root.update()
        time.sleep(0.01)
    root.update()


def _layout_report(root: tk.Tk, app: Application) -> dict:
    root.update_idletasks()
    width, height = (int(part) for part in root.geometry().split("+", 1)[0].split("x"))
    if width <= 1 or height <= 1 or (width, height) == (200, 200):
        width, height = 1080, 760
    requested = [root.winfo_reqwidth(), root.winfo_reqheight()]
    fixed_height = requested[1] - app.tree.winfo_reqheight()
    _assert(requested[0] <= width and fixed_height < height,
            f"Fixed GUI controls overflow: requested={requested}, window={width}x{height}")
    controls = {}
    for name in ("add_button", "folder_button", "output_entry", "start_button",
                 "cancel_button", "status_label", "tree", "details_text"):
        widget = getattr(app, name)
        _assert(bool(widget.winfo_manager()), f"Unmanaged control: {name}")
        _assert(widget.winfo_reqwidth() > 0 and widget.winfo_reqheight() > 0,
                f"Empty control: {name}")
        controls[name] = {
            "requested": [widget.winfo_reqwidth(), widget.winfo_reqheight()],
            "managed_by": widget.winfo_manager(),
        }
    return {"window_state": root.state(), "configured": [width, height],
            "requested": requested, "fixed_content_height": fixed_height,
            "controls": controls}


def run_verification(report_dir: Path) -> dict:
    """Create fixtures, test the real backend and Tk queue, and save report.json."""
    started = time.monotonic()
    deadline = started + 180.0
    report_dir = Path(report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report = {
        "passed": False, "frozen": bool(getattr(sys, "frozen", False)),
        "python": sys.version, "executable": sys.executable,
        "report_path": str(report_path), "checks": {},
    }
    root = None
    app = None
    callback_errors: list[str] = []
    source_hashes: dict[str, str] = {}
    try:
        ffmpeg = ffmpeg_path().resolve(strict=True)
        bundle = Path(sys._MEIPASS).resolve() if hasattr(sys, "_MEIPASS") else None
        bundled = bool(bundle and ffmpeg.is_relative_to(bundle))
        report["resources"] = {
            "ffmpeg": str(ffmpeg), "size": ffmpeg.stat().st_size,
            "bundle_root": str(bundle) if bundle else None, "ffmpeg_in_bundle": bundled,
        }
        if report["frozen"]:
            _assert(bundled, "Frozen self-test must use bundled FFmpeg, not PATH.")
        fixtures = report_dir / ("fixtures-中文 (验收)-" + uuid.uuid4().hex[:8])
        fixtures.mkdir()
        originals = fixtures / "reference"
        originals.mkdir()
        sources = fixtures / "sources"
        sources.mkdir()
        nested = sources / "子目录 日本語"
        nested.mkdir()
        output = sources / "MP3输出"
        output.mkdir()
        report["fixture_root"] = str(fixtures)
        reference_files = {}
        for fmt, codec in (("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
                           ("flac", ["-c:a", "flac"]),
                           ("wav", ["-c:a", "pcm_s16le"]),
                           ("ogg", ["-c:a", "libvorbis", "-q:a", "5"])):
            target = originals / ("two-second-tone." + fmt)
            _run_ffmpeg(ffmpeg, [
                "-v", "error", "-f", "lavfi", "-i",
                "sine=frequency=523:sample_rate=44100:duration=2",
                "-ac", "2", *codec, str(target),
            ], deadline)
            reference_files[fmt] = target
        report["checks"]["two_second_reference_audio_generated"] = True
        png = _tiny_png()
        tags = {"musicName": "离线测试 中文标题", "artist": [["测试歌手甲", 1], ["歌手乙", 2]],
                "album": "批量验收专辑", "format": "mp3"}
        expected_tags = {"title": tags["musicName"], "artist": "测试歌手甲 / 歌手乙",
                         "album": tags["album"]}
        mp3_audio = reference_files["mp3"].read_bytes()
        flac_audio = reference_files["flac"].read_bytes()
        positive_specs = [
            ("02 中文封面 (同名保护).ncm", sources, mp3_audio, "mp3",
             dict(cover=png, cover_padding=73), tags, expected_tags, False),
            ("03 无损转MP3.ncm", nested, flac_audio, "flac", {},
             {**tags, "format": "flac"}, expected_tags, False),
            ("04 无元数据.ncm", sources, mp3_audio, "mp3", {}, None, {}, False),
            ("05 元数据损坏仍可播放.ncm", sources, flac_audio, "flac",
             dict(corrupt_metadata=True), None, {}, True),
            ("06 电台DJ.ncm", sources, mp3_audio, "mp3", dict(dj=True),
             tags, expected_tags, False),
        ]
        positive_paths = []
        extract_reports = []
        for number, (name, directory, audio, fmt, options, metadata,
                     wanted_tags, wanted_warning) in enumerate(positive_specs):
            source = directory / name
            source.write_bytes(_ncm_fixture(audio, metadata, **options))
            positive_paths.append(source)
            extraction_dir = fixtures / f"extracted-{number}"
            extraction_dir.mkdir()
            progress = []
            extracted, actual_fmt, actual_tags, cover, warnings = extract_ncm(
                source, extraction_dir, progress=progress.append)
            _assert(extracted.read_bytes() == audio, f"Raw audio round-trip mismatch: {name}")
            _assert(actual_fmt == fmt, f"Format mismatch: {name}")
            _assert(actual_tags == wanted_tags, f"Metadata mismatch: {name}: {actual_tags!r}")
            _assert(bool(warnings) == wanted_warning, f"Warning mismatch: {name}: {warnings!r}")
            if options.get("cover"):
                _assert(cover is not None and Path(cover).read_bytes() == png,
                        "Embedded cover or reserved cover padding was parsed incorrectly.")
            else:
                _assert(cover is None, f"Unexpected cover: {name}")
            _assert(bool(progress), "Extraction never reported progress.")
            extract_reports.append({
                "source": str(source), "format": actual_fmt, "tags": actual_tags,
                "audio_sha256": _sha256(extracted),
                "reference_sha256": hashlib.sha256(audio).hexdigest(),
                "cover_sha256": _sha256(Path(cover)) if cover else None,
                "warnings": warnings,
            })
        report["extractions"] = extract_reports
        report["checks"].update({
            "mp3_flac_audio_exact_roundtrip": True, "cover_reserved_padding": True,
            "missing_metadata_supported": True, "damaged_metadata_is_warning": True,
            "dj_metadata_supported": True,
        })
        ordinary_paths = []
        for number, fmt in enumerate(("wav", "ogg"), start=7):
            source = sources / f"{number:02} 普通音频.{fmt}"
            source.write_bytes(reference_files[fmt].read_bytes())
            ordinary_paths.append(source)
        mgg_paths = []
        qmc_reports = []
        for number, footer, encv2 in ((9, "V1", True), (10, "QTag", False)):
            source = nested / f"{number:02} 合成内嵌密钥-{footer}.mgg"
            original_ogg = reference_files["ogg"].read_bytes()
            source.write_bytes(_mgg_fixture(original_ogg, footer=footer, encv2=encv2))
            mgg_paths.append(source)
            extraction_dir = fixtures / f"qmc-extracted-{footer}"
            extraction_dir.mkdir()
            prepared = _prepare_audio(source, extraction_dir, None, lambda _text: None)
            decoded, fmt = prepared[:2]
            _assert(fmt == "ogg" and Path(decoded).read_bytes() == original_ogg,
                    f"QMC2 {footer}/EncV{2 if encv2 else 1} round-trip mismatch.")
            qmc_reports.append({
                "source": str(source), "footer": footer, "cipher": "QMC2 short-key Map",
                "key_envelope": "EncV2" if encv2 else "EncV1",
                "decoded_sha256": _sha256(Path(decoded)),
                "reference_sha256": hashlib.sha256(original_ogg).hexdigest(),
            })
        report["qmc_extractions"] = qmc_reports
        report["checks"]["mgg_v1_encv2_exact_roundtrip"] = True
        report["checks"]["mgg_qtag_encv1_exact_roundtrip"] = True

        base = _ncm_fixture(mp3_audio, tags)
        key_length = struct.unpack_from("<I", base, 10)[0]
        meta_length_offset = 14 + key_length
        meta_length = struct.unpack_from("<I", base, meta_length_offset)[0]
        cover_length_offset = meta_length_offset + 4 + meta_length + 5
        def replace_u32(blob: bytes, offset: int, value: int) -> bytes:
            return blob[:offset] + struct.pack("<I", value) + blob[offset + 4:]
        malformed = {
            "bad_magic": b"NOT_NCM!" + base[8:],
            "missing_key_length": base[:12],
            "oversized_key_length": replace_u32(base, 10, 0xFFFFFFFF),
            "unaligned_key_length": replace_u32(base, 10, 17),
            "truncated_key": base[:25],
            "oversized_metadata": replace_u32(base, meta_length_offset, 0xFFFFFFFF),
            "truncated_metadata": base[:meta_length_offset + 8],
            "invalid_cover_capacity": replace_u32(base, cover_length_offset + 4, 50),
            "truncated_cover_frame": replace_u32(base, cover_length_offset, len(base)),
            "empty_stream_key": _ncm_fixture(mp3_audio, tags, empty_key=True),
            "empty_audio": _ncm_fixture(b"", tags),
            "unrecognized_audio": _ncm_fixture(b"not an audio stream" * 20, tags),
        }
        rejected = []
        invalid_dir = fixtures / "malformed"
        invalid_dir.mkdir()
        for name, data in malformed.items():
            source = invalid_dir / (name + ".ncm")
            source.write_bytes(data)
            destination = invalid_dir / (name + "-output")
            destination.mkdir()
            try:
                extract_ncm(source, destination)
            except ValueError as error:
                message = str(error)
                _assert(len(message) >= 5, f"Unhelpful error for {name}: {message!r}")
                rejected.append({"case": name, "message": message})
            else:
                raise AssertionError(f"Malformed fixture was accepted: {name}")
        report["rejected_inputs"] = rejected
        report["checks"]["malformed_inputs_rejected"] = True

        invalid_ncm = sources / "00 无效NCM.ncm"
        invalid_ncm.write_bytes(malformed["bad_magic"])
        corrupt_ogg = sources / "01 损坏音频.ogg"
        corrupt_ogg.write_bytes(b"OggS" + b"invalid-page\0" * 20)
        successful_inputs = [*positive_paths, *ordinary_paths, *mgg_paths]
        inputs = [invalid_ncm, corrupt_ogg, *successful_inputs]
        tracked = [*inputs, *reference_files.values()]
        source_hashes = {str(path): _sha256(path) for path in tracked}
        sentinel = output / (positive_paths[0].stem + ".mp3")
        sentinel_bytes = b"EXISTING OUTPUT MUST NOT BE OVERWRITTEN\n"
        sentinel.write_bytes(sentinel_bytes)

        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda kind, value, tb: callback_errors.append(
            "".join(traceback.format_exception(kind, value, tb)))
        app = Application(root)
        app.output_dir.set(str(output))
        app.output_is_custom = True
        app.bitrate.set("192k")
        report["tk"] = {"version": root.tk.call("info", "patchlevel"),
                        "scaling": root.tk.call("tk", "scaling")}
        report["geometry"] = _layout_report(root, app)
        app.add_paths([sources])
        _pump_until_idle(root, app, deadline)
        _assert({str(row["path"]) for row in app.items.values()} == {str(p) for p in inputs},
                "Recursive folder scan lost an input or included the output folder.")
        app.add_paths(inputs)
        _pump_until_idle(root, app, deadline)
        _assert(len(app.items) == len(inputs), "Duplicate import created duplicate jobs.")
        report["checks"]["recursive_scan_and_duplicate_protection"] = True
        app._start()
        _assert(app.mode == "converting", "Tk did not start the real background worker.")
        _pump_until_idle(root, app, deadline)
        rows = [{**row, "path": str(row["path"])} for row in app.items.values()]
        report["queue"] = rows
        report["summary"] = app.summary.get()
        report["status"] = app.status.get()
        by_path = {row["path"]: row for row in rows}
        successes = [row for row in rows if row["status"] == "成功"]
        failures = [row for row in rows if row["status"] == "失败"]
        _assert(len(successes) == len(successful_inputs) and len(failures) == 2,
                f"Mixed batch expected {len(successful_inputs)} successes/2 failures, "
                f"got {len(successes)}/{len(failures)}.")
        for source in successful_inputs:
            _assert(by_path[str(source)]["status"] == "成功", f"Valid input failed: {source}")
        for source in (invalid_ncm, corrupt_ogg):
            row = by_path[str(source)]
            _assert(row["status"] == "失败" and len(row["message"]) >= 8,
                    f"Invalid file did not receive a useful failure: {source}")
        warning_row = by_path[str(positive_paths[3])]
        _assert(warning_row.get("has_warnings") and "歌曲信息" in warning_row["message"],
                "Optional metadata warning was not retained in the GUI.")
        warning_iid = next(iid for iid, item in app.items.items()
                           if item["path"] == positive_paths[3])
        app.tree.selection_set(warning_iid)
        app._show_selected_details()
        _assert("歌曲信息" in app.details_text.get("1.0", "end"),
                "The selected-row details omitted its warning.")
        report["checks"]["mixed_batch_continues_after_failures"] = True
        report["checks"]["ncm_mgg_wav_ogg_mixed_batch"] = True
        report["checks"]["warnings_visible_in_gui_details"] = True
        _assert(sentinel.read_bytes() == sentinel_bytes, "Existing MP3 was overwritten.")
        _assert(Path(by_path[str(positive_paths[0])]["output"]) != sentinel,
                "Name collision did not produce a separate output.")
        report["checks"]["same_name_output_preserved"] = True
        output_reports = []
        for row in successes:
            target = Path(row["output"])
            _, log = _run_ffmpeg(ffmpeg, [
                "-v", "info", "-xerror", "-i", str(target), "-map", "0:a:0",
                "-f", "null", "-",
            ], deadline)
            _assert("Input #0, mp3," in log and "Audio: mp3" in log,
                    f"Output is not MP3: {target}")
            output_reports.append({"path": str(target), "size": target.stat().st_size,
                                   "sha256": _sha256(target), "full_decode": "passed"})
        report["outputs"] = output_reports
        report["checks"]["all_mp3_outputs_fully_decodable"] = True
        for source in (positive_paths[0], positive_paths[1], positive_paths[4]):
            target = by_path[str(source)]["output"]
            text, _ = _run_ffmpeg(ffmpeg, [
                "-v", "error", "-i", target, "-map_metadata", "0",
                "-f", "ffmetadata", "pipe:1",
            ], deadline)
            fields = dict(line.split("=", 1) for line in text.splitlines()
                          if "=" in line and not line.startswith(";"))
            _assert(all(fields.get(key) == value for key, value in expected_tags.items()),
                    f"MP3 Chinese metadata mismatch: {fields!r}")
        report["checks"]["chinese_tags_survive_mp3_transcoding"] = True
        tagged_target = Path(by_path[str(positive_paths[0])]["output"])
        cover_result = fixtures / "recovered-cover.png"
        _run_ffmpeg(ffmpeg, [
            "-v", "error", "-i", str(tagged_target), "-map", "0:v:0",
            "-frames:v", "1", "-c:v", "copy", str(cover_result),
        ], deadline)
        _assert(cover_result.read_bytes() == png, "MP3 embedded cover did not round-trip.")
        report["checks"]["embedded_png_survives_mp3_transcoding"] = True
        _assert(set(output.glob("*.mp3")) == {sentinel, *(Path(row["output"]) for row in successes)},
                "A failed conversion left an unexpected MP3.")
        report["checks"]["failed_jobs_leave_no_mp3"] = True

        direct_output = fixtures / "direct-warning-result"
        direct = convert_file(positive_paths[3], direct_output, bitrate="256k")
        _assert(direct.get("verified") and direct.get("warnings"),
                "Converter result omitted metadata warnings or verification.")
        report["direct_conversion"] = direct
        report["checks"]["converter_returns_warning_details"] = True
        cancel = threading.Event()
        cancel.set()
        cancelled_output = fixtures / "cancelled-output"
        try:
            convert_file(positive_paths[0], cancelled_output, cancel_event=cancel)
        except ConversionCancelled:
            pass
        else:
            raise AssertionError("Pre-cancelled job did not raise ConversionCancelled.")
        _assert(not cancelled_output.exists(), "Pre-cancelled job created an output directory.")
        report["checks"]["pre_cancelled_conversion_has_no_output"] = True
        after = {path: _sha256(Path(path)) for path in source_hashes}
        report["input_hashes"] = {"before": source_hashes, "after": after}
        _assert(after == source_hashes, "An input fixture or reference audio was modified.")
        report["checks"]["all_sources_unchanged"] = True
        _assert(not callback_errors, "Tk callback errors: " + "\n".join(callback_errors))
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
            if app.worker is not None:
                app.worker.join(timeout=3)
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass
        report["tk_callback_errors"] = callback_errors
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python verify_app.py REPORT_DIRECTORY")
    result = run_verification(Path(sys.argv[1]))
    print(json.dumps({"passed": result["passed"], "report": result["report_path"],
                      "checks": len(result["checks"])}, ensure_ascii=False))
