# 来源与构建记录

本工具版本 2.0.0，适用于 Windows x64。应用代码基于已有本地批量音频转换界面改写；NCM 流式解包代码参考以下公开格式实现：

- [taurusxin/ncmdump](https://github.com/taurusxin/ncmdump)，重点参考 `src/ncmcrypt.cpp` 中密钥、元数据、封面容量和音频起点的处理。
- [ww-rm/ncmdump-py](https://github.com/ww-rm/ncmdump-py)，重点参考 `ncmdump/crypto.py` 的 AES 常量及 256 字节音频掩码。

上述参考为开源逆向实现，不是音乐平台发布的官方文件规范。对应 MIT 许可原文位于 `licenses/`。

构建组件：Python 3.12.10、Tcl/Tk 8.6.15、PyCryptodome 3.23.0、PyInstaller 6.22.3。

- [Python 3.12.10](https://github.com/python/cpython/tree/v3.12.10)
- [PyCryptodome 3.23.0](https://github.com/Legrandin/pycryptodome/tree/v3.23.0)
- [PyInstaller 6.22.3](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)
- [Tcl](https://github.com/tcltk/tcl) / [Tk](https://github.com/tcltk/tk)

打包包含通过独立进程调用的 `FFmpeg 9.0.1-full_build-www.gyan.dev`（GPL v3）。

- [Gyan 原始发布](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.1)
- [FFmpeg 主体源码版本 bf1b838f2a](https://github.com/FFmpeg/FFmpeg/commit/bf1b838f2a)
- 构建参数和外部库版本见 `licenses/FFmpeg-build.txt`。
- ffmpeg.exe SHA-256：`57c56e369d5b4873b4d93fc1a1d833cb7cd8bc9325c14b05c34ce60b22842d8a`。

FFmpeg 主体源码不包含 full 构建的全部外部库；Gyan 发布页自动生成的 Source code 是支持仓库，不应当作完整的 FFmpeg 对应源码包。更换组件时需同步更新对应来源及许可证。

QMC2 核心沿用已验证的 MGG 工具，来自 [QM Unlock](https://github.com/mary20050520/qmunlock/blob/master/qmunlock/qmc2.py)，MIT 许可证见 `licenses/QMunlock-MIT.txt`。
