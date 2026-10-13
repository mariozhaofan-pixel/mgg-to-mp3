# 第三方来源与发布构建

本项目的转换流程在本机执行。以下记录 v1.0.0 使用的上游代码和构建组件；各组件保留自己的许可证。

| 组件 | 版本或标识 | 上游 |
| --- | --- | --- |
| QMC2 解码核心 | `qmc2_core.py`，SHA-256 `8da32a863d6c3b2fc23bac42eb3eafa15159c0c678c1b14ccfed63bb427eed78` | [QM Unlock](https://github.com/mary20050520/qmunlock)，MIT |
| FFmpeg | `9.0.1-full_build-www.gyan.dev` | [Gyan 发布页](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.1)，GPL v3 |
| FFmpeg 主体源码 | `bf1b838f2a` | [FFmpeg 源码版本](https://github.com/FFmpeg/FFmpeg/commit/bf1b838f2a) |
| Python | 3.12.14 | [CPython](https://github.com/python/cpython/tree/v3.12.14) |
| Tcl / Tk | 8.6.12 | [Tcl](https://github.com/tcltk/tcl/tree/core-8-6-12)、[Tk](https://github.com/tcltk/tk/tree/core-8-6-12) |
| PyInstaller | 6.22.3 | [PyInstaller](https://github.com/pyinstaller/pyinstaller/tree/v6.22.3)，引导程序带分发例外 |

QMC2 核心原始文件：[qmunlock/qmc2.py](https://github.com/mary20050520/qmunlock/blob/master/qmunlock/qmc2.py)。固定算法常量属于该解码实现，不是登录凭据。

FFmpeg 通过独立子进程调用；发布 EXE 包含该程序。其原始构建信息及依赖版本清单见 [licenses/FFmpeg-build.txt](licenses/FFmpeg-build.txt)，许可证见 [licenses/FFmpeg-GPLv3.txt](licenses/FFmpeg-GPLv3.txt)。该 `ffmpeg.exe` 的 SHA-256 为：

```text
57c56e369d5b4873b4d93fc1a1d833cb7cd8bc9325c14b05c34ce60b22842d8a
```

上述 FFmpeg 主体链接不包含 full 静态构建的全部外部库。Gyan 发布页的自动 “Source code” 下载是其支持仓库；本页不将它表述为完整的 FFmpeg 对应源码包。[Gyan 的构建工具仓库](https://github.com/GyanD/media-autobuild_suite) 可供参考，但尚未核实为此二进制的精确构建脚本。

若替换 FFmpeg，自行构建者需同步核对版本、构建信息、依赖来源和许可证。仓库 `LICENSE` 中的 MIT 授权不改变第三方组件的授权条款。
