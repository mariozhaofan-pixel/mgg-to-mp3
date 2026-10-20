# 音乐批量转 MP3

版本 **2.0.0**。Windows 中文图形界面工具，将 NCM、MGG / MFLAC 和普通音频放进同一个列表，自动识别并统一转为 MP3。支持批量文件、递归文件夹、失败继续、取消任务和同名保护。

**[下载最新 Windows 版本](https://github.com/mariozhaofan-pixel/mgg-to-mp3/releases/latest)**。仓库沿用 `mgg-to-mp3` 名称，v2.0.0 起为包含 NCM 与普通音频的统一工具。

## 直接使用

1. 下载 `Music-to-MP3-v2.0.0-win64.zip` 并解压，双击其中的 `Music-to-MP3.exe`（本地构建名称为 `音乐批量转MP3.exe`），无需安装 Python、FFmpeg 或音乐客户端。
2. 点击「添加文件」选择多个音频文件，或点击「添加文件夹」。不同格式可以混合添加，也可以将文件拖到 EXE 图标上启动。
3. 选择输出目录和 192 / 256 / 320 kbps 码率，点击「开始转换」。
4. 完成后点击「打开输出」。失败或有提示时，选中该行查看详情。

默认输出到首个输入文件所在目录或首个输入文件夹下的 `MP3输出`。源文件保持不变，已有同名 MP3 会自动避让。每个结果均通过完整音频解码检查后才保存。递归导入时会排除当前输出目录及其子目录，避免重复转换。

## 支持范围

| 输入类型 | 处理方式 |
| --- | --- |
| NCM | 解包标准 NCM，将音频转为 MP3，并保留可读取的歌曲名、歌手、专辑和内嵌封面 |
| MGG / MFLAC | 继承原 MGG 工具的 QMC2 内嵌密钥解码，解码后转为 MP3 |
| 普通音频 | 支持 WAV、OGG、FLAC、Opus、M4A、MP3、AAC、WMA、AIF、AIFF、APE，由 FFmpeg 读取并转码 |

**需要外部 `musicex` 密钥的新版 MGG 不支持。** 不同 MGG 文件可能采用不同结构，本工具仅支持能够从文件内解析密钥的版本。普通音频也必须具有完整、有效且可解码的内容；扩展名正确不等于文件有效。

NCM 中损坏或无法读取的元数据、封面会跳过并显示提示，不联网获取封面。全部处理在本地进行，不上传音频，不读取账号登录凭据。音质取决于源文件，较高码率不能恢复已经损失的细节。

## 常见问题

- NCM 是封装，内含 MP3 或 FLAC 等编码；MGG / MFLAC 也可能封装加密音频。本工具会解码后继续转码，最终统一生成 MP3。
- 请使用完整的原始文件；仅修改文件扩展名没有作用。其他工具解密失败后生成的伪 OGG 文件不能直接转码，应添加原始 MGG 重试。
- 损坏、不完整或尚未支持的文件会报错，其余文件继续处理。标记「成功（提示）」的文件已经生成 MP3，选中后可查看附加说明。
- 首次启动略慢属于单文件 EXE 解压内置组件的过程。
- 右上角「关于」可查看版本和第三方许可证；许可证目录在工具运行期间可打开。

## 源码运行和构建

使用 Windows x64、Python 3.12（含 Tkinter）和支持 `libmp3lame` 的 FFmpeg。运行依赖与构建依赖保持在 `requirements.txt` 和 `requirements-build.txt` 中，构建使用 PyInstaller 6.22.3：

```powershell
python -m pip install -r requirements-build.txt
$env:AUDIO_FFMPEG = 'C:\Tools\ffmpeg\bin\ffmpeg.exe'
python launcher.py
.\build.ps1 -FFmpegExe $env:AUDIO_FFMPEG
```

如果 `ffmpeg.exe` 已在 `PATH` 中，可省略 `AUDIO_FFMPEG` 环境变量，并直接运行 `.\build.ps1`。打包后的 EXE 使用内置 FFmpeg，不需要设置环境变量。

构建输出为项目上一级 `发布` 文件夹中的 `音乐批量转MP3.exe`。预生成图标已包含；仅重新生成图标需要 Pillow。

离线验收会生成自己的音频与 NCM 测试夹具，不包含真实歌曲：

```powershell
python launcher.py --self-test .verification-source
```

## 许可与来源

本项目原创应用代码采用 MIT 授权。NCM 格式参考 MIT 项目 [taurusxin/ncmdump](https://github.com/taurusxin/ncmdump) 和 [ww-rm/ncmdump-py](https://github.com/ww-rm/ncmdump-py)。MGG / QMC2 算法代码来自 MIT 项目 [QM Unlock](https://github.com/mary20050520/qmunlock)，保留原作者许可证。本项目不是音乐平台的官方工具。

FFmpeg、Python、Tcl/Tk、PyCryptodome 和 PyInstaller 使用各自的许可证，详见 `THIRD_PARTY.txt`、`SOURCES.md` 和 `licenses/`。整个 EXE 及所有依赖不能统称为 MIT 授权。本项目不附带音乐文件。
