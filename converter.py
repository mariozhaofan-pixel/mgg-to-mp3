"""Local batch-conversion backend. Original inputs are never modified."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from ncm_core import MAGIC, audio_format, extract_ncm
from qmc_reader import extract_qmc

QMC_EXTENSIONS = {
    '.mgg', '.mgg0', '.mgg1', '.mgg2', '.mggl', '.mflac',
    '.mflac0', '.mflac1', '.mflac2', '.qmcogg', '.qmcflac',
}
PLAIN_EXTENSIONS = {'.ogg', '.opus', '.flac', '.m4a', '.wav', '.mp3',
                    '.aac', '.wma', '.aif', '.aiff', '.ape'}
SUPPORTED_EXTENSIONS = {'.ncm'} | QMC_EXTENSIONS | PLAIN_EXTENSIONS


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
        external = os.environ.get("AUDIO_FFMPEG") or os.environ.get("NCM_FFMPEG") or os.environ.get("MGG_FFMPEG") or shutil.which("ffmpeg")
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


def _prepare_audio(source: Path, temp: Path, event, progress):
    _check_cancel(event)
    with source.open('rb') as file:
        header = file.read(64)
    if header.startswith(MAGIC):
        return extract_ncm(source, temp, lambda: _check_cancel(event), progress)
    if source.suffix.lower() == '.ncm':
        raise ValueError('这不是有效的 NCM 文件；文件可能损坏，或只是修改了扩展名。')
    if source.suffix.lower() in QMC_EXTENSIONS:
        decoded, fmt = extract_qmc(source, temp, lambda: _check_cancel(event), progress)
        return decoded, fmt, {}, None, []
    fmt = audio_format(header)
    if not fmt and source.suffix.lower() in PLAIN_EXTENSIONS:
        fmt = source.suffix.lower().lstrip('.')
    if not fmt:
        raise ValueError('未识别到有效音频，请使用原始 NCM / MGG 或可播放的普通音频。')
    return source, fmt, {}, None, []


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
    with tempfile.TemporaryDirectory(prefix="audio-mp3-") as folder:
        temp = Path(folder)
        decoded, decoded_format, tags, cover, warnings = _prepare_audio(source, temp, cancel_event, progress)
        encoded = temp / "output.mp3"
        progress("正在转为 MP3")
        def encode(include_cover):
            command = [executable, '-hide_banner', '-nostdin', '-v', 'error', '-xerror',
                       '-nostats', '-progress', 'pipe:1', '-n', '-i', str(decoded)]
            if include_cover:
                command += ['-i', str(cover)]
            command += ['-map', '0:a:0', '-map_metadata', '0', '-map_metadata', '0:s:a:0']
            if include_cover:
                command += ['-map', '1:v:0', '-c:v', 'copy', '-disposition:v:0', 'attached_pic',
                            '-metadata:s:v', 'title=Album cover', '-metadata:s:v', 'comment=Cover (front)']
            else:
                command += ['-vn']
            for key, value in tags.items():
                command += ['-metadata', f'{key}={value}']
            command += ['-c:a', 'libmp3lame', '-b:a', bitrate, '-id3v2_version', '3', str(encoded)]
            return _run(command, cancel_event)
        try:
            stdout, _ = encode(bool(cover))
        except RuntimeError:
            if not cover:
                raise
            encoded.unlink(missing_ok=True)
            stdout, _ = encode(False)
            warnings.append('内嵌封面无法写入，已保存不含封面的 MP3。')
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
        "decoded_format": decoded_format, "verified": True, "warnings": warnings,
    }
