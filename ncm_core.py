"""Bounded, streaming NCM reader. Format references are recorded in SOURCES.md.

No account access, cover downloads, or network requests are made here.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import struct

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from Crypto.Util.strxor import strxor

MAGIC = b"CTENFDAM"
# Public constants from the NCM container format, not account credentials.
CORE_KEY = bytes.fromhex("687A4852416D736F356B496E62617857")
META_KEY = bytes.fromhex("2331346C6A6B5F215C5D2630553C2728")
META_PREFIX = b"163 key(Don't modify):"


def audio_format(data: bytes) -> str | None:
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if data.startswith(b"OggS"):
        return "ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[4:8] == b"ftyp":
        return "m4a"
    return None


def _read(stream, count: int) -> bytes:
    data = stream.read(count)
    if len(data) != count:
        raise ValueError("NCM 文件不完整：数据长度不足，请重新下载原文件。")
    return data


def _u32(stream) -> int:
    return struct.unpack("<I", _read(stream, 4))[0]


def _keystream(key: bytes) -> bytes:
    if not key:
        raise ValueError("NCM 音频密钥为空。")
    box = list(range(256))
    j = 0
    for i in range(256):
        j = (box[i] + j + key[i % len(key)]) & 255
        box[i], box[j] = box[j], box[i]
    return bytes(box[(box[(i + 1) & 255] + box[(box[(i + 1) & 255] + ((i + 1) & 255)) & 255]) & 255]
                 for i in range(256))


def _metadata(data: bytes) -> dict:
    raw = bytes(value ^ 0x63 for value in data)
    if not raw.startswith(META_PREFIX):
        raise ValueError("未知歌曲信息格式")
    encrypted = base64.b64decode(raw[len(META_PREFIX):], validate=True)
    plain = unpad(AES.new(META_KEY, AES.MODE_ECB).decrypt(encrypted), 16)
    if plain.startswith(b"music:"):
        info = json.loads(plain[6:].decode("utf-8"))
    elif plain.startswith(b"dj:"):
        info = json.loads(plain[3:].decode("utf-8"))
        info = info.get("mainMusic", info) if isinstance(info, dict) else {}
    else:
        raise ValueError("未知歌曲信息类型")
    return info if isinstance(info, dict) else {}


def _tags(info: dict) -> dict[str, str]:
    result = {}
    for field, tag in (("musicName", "title"), ("album", "album")):
        value = info.get(field)
        if isinstance(value, (str, int)):
            result[tag] = str(value).replace("\0", "")[:4096]
    artists = info.get("artist", [])
    if isinstance(artists, list):
        names = [artist[0] if isinstance(artist, list) and artist else artist for artist in artists]
        result["artist"] = " / ".join(name for name in names if isinstance(name, str)).replace("\0", "")[:4096]
    elif isinstance(artists, str):
        result["artist"] = artists.replace("\0", "")[:4096]
    return {key: value for key, value in result.items() if value}


def extract_ncm(source: Path, directory: Path, check_cancel=lambda: None, progress=lambda _message: None):
    """Return decoded path, detected format, tags, embedded cover and warnings."""
    warnings = []
    info = {}
    cover_path = None
    with source.open("rb") as stream:
        size = source.stat().st_size
        if _read(stream, 8) != MAGIC:
            raise ValueError("这不是有效的 NCM 文件；修改扩展名不能转换音频。")
        _read(stream, 2)
        key_size = _u32(stream)
        if not 16 <= key_size <= 65536 or key_size % 16:
            raise ValueError("NCM 密钥区长度无效，文件可能损坏或格式不受支持。")
        encrypted_key = bytes(value ^ 0x64 for value in _read(stream, key_size))
        try:
            key = unpad(AES.new(CORE_KEY, AES.MODE_ECB).decrypt(encrypted_key), 16)
        except ValueError as error:
            raise ValueError("NCM 音频密钥无法解析。") from error
        if not key.startswith(b"neteasecloudmusic"):
            raise ValueError("NCM 密钥标记不正确，无法读取此版本。")
        mask = _keystream(key[17:])
        metadata_size = _u32(stream)
        if metadata_size > 4 * 1024 * 1024 or stream.tell() + metadata_size > size:
            raise ValueError("NCM 歌曲信息区长度无效。")
        metadata = _read(stream, metadata_size)
        if metadata:
            try:
                info = _metadata(metadata)
            except (ValueError, UnicodeError, TypeError, RecursionError):
                warnings.append("歌曲信息无法解析，已保留可读取的音频。")
        _read(stream, 5)  # CRC32 and image version
        cover_frame_size = _u32(stream)
        cover_size = _u32(stream)
        if cover_size > cover_frame_size or cover_frame_size > 32 * 1024 * 1024:
            raise ValueError("NCM 封面区长度无效。")
        if stream.tell() + cover_frame_size >= size:
            raise ValueError("NCM 文件缺少音频，或封面区不完整。")
        cover = _read(stream, cover_size)
        stream.seek(cover_frame_size - cover_size, 1)
        if cover:
            suffix = ".png" if cover.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if cover.startswith(b"\xff\xd8\xff") else None
            if suffix:
                cover_path = directory / ("cover" + suffix)
                cover_path.write_bytes(cover)
            else:
                warnings.append("封面格式无法识别，已跳过封面。")
        decoded = directory / "decoded.audio"
        offset = 0
        fmt = None
        progress("正在解码 NCM")
        with decoded.open("wb") as target:
            while True:
                check_cancel()
                block = stream.read(128 * 1024)
                if not block:
                    break
                shift = offset % 256
                current_mask = mask[shift:] + mask[:shift]
                plain = strxor(block, (current_mask * ((len(block) + 255) // 256))[:len(block)])
                if offset == 0:
                    fmt = audio_format(plain[:64])
                    if not fmt:
                        raise ValueError("NCM 解码结果不是可识别的音频，文件可能损坏或格式不受支持。")
                target.write(plain)
                offset += len(block)
        if not offset:
            raise ValueError("NCM 文件没有音频数据。")
    return decoded, fmt, _tags(info), cover_path, warnings
