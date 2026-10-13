"""Local batch-conversion backend. Original inputs are never modified."""
from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from qmc2_core import RC4, derive_key, detect_fmt, map_decrypt

SUPPORTED_EXTENSIONS = {
    ".mgg", ".mgg0", ".mgg1", ".mgg2", ".mggl", ".mflac",
    ".mflac0", ".mflac1", ".mflac2", ".qmcogg", ".qmcflac",
    ".ogg", ".opus", ".flac", ".m4a", ".wav", ".mp3",
}


class ConversionCancelled(Exception):
    pass


def _check_cancel(event):
    if event is not None and event.is_set():
        raise ConversionCancelled("已取消")


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def ffmpeg_path() -> Path:
    bundled = resource_path("bin/ffmpeg.exe")
    if bundled.is_file():
        return bundled
    if not getattr(sys, "frozen", False):
        external = os.environ.get("MGG_FFMPEG") or shutil.which("ffmpeg")
        if external and Path(external).is_file():
            return Path(external)
    raise RuntimeError("未找到内置转码组件，请重新下载完整的工具。")


def _run(command: list[str], event=None) -> tuple[str, str]:
    _check_cancel(event)
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    started = time.monotonic()
    try:
        while True:
            _check_cancel(event)
            if time.monotonic() - started > 3600:
                raise RuntimeError("处理超过一小时，已停止；请检查文件是否损坏。")
            try:
                stdout, stderr = process.communicate(timeout=0.15)
                break
            except subprocess.TimeoutExpired:
                continue
        _check_cancel(event)
        if process.returncode:
            detail = stderr.strip()[-1800:]
            raise RuntimeError("音频读取或转码失败：" + (detail or f"退出码 {process.returncode}"))
        return stdout, stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def _plain_format(header: bytes) -> str | None:
    if len(header) < 12:
        return None
    result = detect_fmt(header)
    if result != "bin":
        return result
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    return None


def _prepare_audio(source: Path, temp: Path, event, progress) -> tuple[Path, str]:
    _check_cancel(event)
    with source.open("rb") as file:
        header = file.read(64)
        plain_format = _plain_format(header)
        if plain_format:
            return source, plain_format
        size = file.seek(0, os.SEEK_END)
        if size < 16:
            raise ValueError("文件过短或不完整，无法读取音频。")
        file.seek(-8, os.SEEK_END)
        tail = file.read(8)
        if tail == b"musicex\0":
            raise ValueError("这是需要外部密钥的新版 MGG；本工具支持自带密钥的文件，无法处理这一首。")
        if tail[-4:] == b"QTag":
            footer_size = int.from_bytes(tail[:4], "big")
            footer_end = size - 8
            kind = "QTag"
        else:
            footer_size = int.from_bytes(tail[-4:], "little")
            footer_end = size - 4
            kind = "V1"
        if not 0 < footer_size <= min(16384, footer_end):
            raise ValueError("未识别到有效音频或内嵌密钥；请添加原始 MGG，不要使用转换失败的 OGG。")
        payload_end = footer_end - footer_size
        if payload_end < 16:
            raise ValueError("文件缺少完整的音频数据。")
        file.seek(payload_end)
        ekey = file.read(footer_size)
        if kind == "QTag":
            ekey = ekey.split(b",", 1)[0]
        ekey = ekey.rstrip(b"\0\r\n ")
        try:
            base64.b64decode(ekey, validate=True)
            key = derive_key(ekey)
        except (ValueError, binascii.Error, IndexError) as exc:
            raise ValueError("文件内的密钥无法解析，可能是不支持的版本或下载不完整。") from exc
        progress("正在解密")
        rc4 = RC4(key) if len(key) > 300 else None
        decoded_path = temp / "decoded.audio"
        offset = 0
        decoded_format = None
        file.seek(0)
        with decoded_path.open("wb") as decoded:
            while offset < payload_end:
                _check_cancel(event)
                block = bytearray(file.read(min(128 * 1024, payload_end - offset)))
                if not block:
                    raise ValueError("读取到不完整的文件，请重新下载原始 MGG。")
                if rc4:
                    rc4.decrypt_into(block, offset)
                else:
                    map_decrypt(block, key, offset)
                if offset == 0:
                    decoded_format = _plain_format(block[:64])
                    if not decoded_format:
                        raise ValueError("解密结果不是有效音频，已停止；未生成伪装成 OGG 的错误文件。")
                decoded.write(block)
                offset += len(block)
        return decoded_path, decoded_format


def _duration(progress_text: str) -> float:
    value = 0.0
    for line in progress_text.splitlines():
        if line.startswith("out_time_us="):
            try:
                value = max(value, int(line.partition("=")[2]) / 1_000_000)
            except ValueError:
                pass
    return value


def _publish(temp: Path, directory: Path, stem: str, event) -> Path:
    """Exclusive create handles name collisions without overwriting user files."""
    for number in range(1, 10001):
        _check_cancel(event)
        name = f"{stem}.mp3" if number == 1 else f"{stem} ({number}).mp3"
        target = directory / name
        try:
            output = target.open("xb")
        except FileExistsError:
            continue
        try:
            with output, temp.open("rb") as source:
                while block := source.read(1024 * 1024):
                    _check_cancel(event)
                    output.write(block)
            return target
        except BaseException:
            # target was created exclusively by this function, never a source file.
            target.unlink(missing_ok=True)
            raise
    raise RuntimeError("输出目录中同名文件过多，请换一个输出目录。")


def convert_file(
    source: Path,
    output_dir: Path,
    bitrate: str = "320k",
    cancel_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    progress = progress or (lambda _text: None)
    _check_cancel(cancel_event)
    source = Path(source).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    if not source.is_file():
        raise ValueError("请选择音频文件。")
    if bitrate not in {"192k", "256k", "320k"}:
        raise ValueError("不支持的 MP3 码率。")
    executable = str(ffmpeg_path())
    output_dir.mkdir(parents=True, exist_ok=True)
    progress("正在读取")
    with tempfile.TemporaryDirectory(prefix="mgg-mp3-") as folder:
        temp = Path(folder)
        decoded, decoded_format = _prepare_audio(source, temp, cancel_event, progress)
        encoded = temp / "output.mp3"
        progress("正在转为 MP3")
        stdout, _ = _run([
            executable, "-hide_banner", "-nostdin", "-v", "error", "-xerror",
            "-nostats", "-progress", "pipe:1", "-n", "-i", str(decoded),
            "-map", "0:a:0", "-map_metadata", "0", "-map_metadata", "0:s:a:0",
            "-vn", "-c:a", "libmp3lame", "-b:a", bitrate,
            "-id3v2_version", "3", str(encoded),
        ], cancel_event)
        if not encoded.is_file() or encoded.stat().st_size < 100:
            raise RuntimeError("未生成完整的 MP3 文件。")
        progress("正在验证")
        checked, _ = _run([
            executable, "-hide_banner", "-nostdin", "-v", "error", "-xerror",
            "-nostats", "-progress", "pipe:1", "-i", str(encoded),
            "-map", "0:a:0", "-f", "null", "-",
        ], cancel_event)
        duration = _duration(checked)
        if duration <= 0:
            raise RuntimeError("MP3 没有可播放的音频。")
        encoded_duration = _duration(stdout)
        if encoded_duration > 0 and abs(duration - encoded_duration) > 0.3:
            raise RuntimeError("转换前后时长不一致，未保存不完整的结果。")
        progress("正在保存")
        target = _publish(encoded, output_dir, source.stem, cancel_event)
    return {
        "source": str(source), "output": str(target), "duration": duration,
        "bitrate": bitrate, "size": target.stat().st_size,
        "decoded_format": decoded_format, "verified": True,
    }
