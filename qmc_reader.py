"""Embedded-key QMC2 decoding, preserved from the verified MGG converter."""
import base64
import binascii
import os
from pathlib import Path
from qmc2_core import RC4, derive_key, detect_fmt, map_decrypt

def _plain_format(header: bytes) -> str | None:
    if len(header) < 12:
        return None
    result = detect_fmt(header)
    if result != "bin":
        return result
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    return None


def extract_qmc(source: Path, temp: Path, check_cancel=lambda: None, progress=lambda _text: None) -> tuple[Path, str]:
    check_cancel()
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
                check_cancel()
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

