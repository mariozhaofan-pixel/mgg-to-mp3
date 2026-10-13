# MGG 批量转 MP3

一个 Windows 本地批量转换工具。双击 EXE，添加音乐文件或文件夹，即可把支持的 MGG / QMC2 文件及普通音频转换为 MP3。

**[下载最新 Windows 版本](https://github.com/mariozhaofan-pixel/mgg-to-mp3/releases/latest)** · 当前版本：`1.0.0`

## 使用方法

1. 从 Releases 下载 `MGG批量转MP3.exe`，保存后双击运行。无需安装 Python 或另外配置 FFmpeg。
2. 点击「添加文件」批量选择音乐，或点击「添加文件夹」递归读取子文件夹。
3. 选择输出目录和码率，然后点击「开始转换」。默认输出到首个输入文件所在目录或首个输入文件夹下的 `MP3输出` 文件夹。
4. 转换结束后点击「打开输出」。选中失败的文件可查看具体原因。

文件也可以拖到 EXE 图标上，作为启动参数导入。程序窗口内使用添加按钮导入文件。

## 功能

- 支持批量添加、递归读取文件夹、去重、移除所选和清空列表。
- 可转换自带内嵌密钥的 MGG / MFLAC / QMC2 文件，以及有效的普通 OGG、FLAC、Opus、WAV、M4A、MP3 文件。
- 提供 `320 / 256 / 192 kbps` 三档 MP3 码率，默认 `320 kbps`。
- 逐项显示处理结果；一个文件失败后继续处理其他文件。
- 保留源文件；输出重名时自动另存，不覆盖已有文件。
- 可取消任务；已完成的输出会保留，未完成的临时输出会清理。
- 转码后进行完整解码验证，通过后才保存结果。
- 全程本地处理，不上传音频，不读取账号登录凭据。

添加文件夹时会排除当前配置的输出目录及其子目录，避免重复处理已经生成的 MP3。

## 支持范围与常见失败

**MGG 是扩展名，不代表所有文件采用相同的加密结构。** 本工具处理带可解析内嵌密钥的 QMC2 文件，包括支持的 V1 和 QTag 尾部结构。

- **不支持需要外部密钥的 `musicex` 新格式。** 遇到这类文件会明确提示，不能仅通过改扩展名解决。
- 普通 `.ogg` 必须确实包含有效音频。其他工具解密错误后生成的 `.ogg`，即使扩展名正确，也无法正常转成 MP3。
- 文件损坏、下载不完整或使用不支持的密钥结构时，会显示失败原因。建议使用原始下载文件重试。
- MP3 是有损格式。选择更高码率不会恢复原始音频中已经缺失的细节。

本项目不提供音乐文件。

## 从源码运行

使用 Windows x64、Python 3.12（含 Tkinter）和支持 `libmp3lame` 的 FFmpeg。图形界面只使用 Python 标准库；运行源码不需要 PyInstaller。

确认 Python 的 Tkinter 可用：

```powershell
python -m tkinter
```

在仓库目录中运行：

```powershell
$env:MGG_FFMPEG = 'C:\Tools\ffmpeg\bin\ffmpeg.exe'
python .\launcher.py
```

如果 `ffmpeg.exe` 已在 `PATH` 中，可省略环境变量。`MGG_FFMPEG` 仅用于源码运行；打包后的 EXE 使用随附组件。

## 构建单文件 EXE

构建环境同上，并需要 PowerShell 和 **PyInstaller 6.22.3**。仓库已包含预生成的 `icon.ico`，正常构建不需要 Pillow。

在仓库目录中安装构建依赖：

```powershell
python -m pip install --target .packaging -r .\requirements-build.txt
```

然后运行构建脚本，指定 FFmpeg：

```powershell
.\build.ps1 -PythonExe 'python' -FFmpegExe 'C:\Tools\ffmpeg\bin\ffmpeg.exe'
```

如果 `ffmpeg.exe` 已在 `PATH` 中：

```powershell
.\build.ps1
```

`build.ps1` 会读取仓库下的 `.packaging` 依赖目录，将 FFmpeg、许可证和图标一起打包。生成文件为仓库**上一级** `发布` 目录中的 `MGG批量转MP3.exe`；构建缓存位于仓库内的 `.build` 目录。

如果自行更换 FFmpeg 版本或构建来源，请同步更新 `THIRD_PARTY.txt` 和 `licenses/` 中的版本、构建来源及对应许可证信息。

仅在需要重新生成图标时安装 Pillow 并运行：

```powershell
python -m pip install Pillow
python .\build_icon.py
```

## 许可证与第三方组件

本项目新增的应用代码采用 [MIT 许可证](LICENSE)，版权所有 © 2026 mariozhaofan-pixel。

QMC2 算法代码来自 [QM Unlock](https://github.com/mary20050520/qmunlock)，其原始 MIT 许可证保存在 [licenses/QMunlock-MIT.txt](licenses/QMunlock-MIT.txt)。

发布的 EXE 包含或随附 FFmpeg、Python、Tcl/Tk、PyInstaller 引导程序等第三方组件，分别受各自许可证约束。当前发布所用 FFmpeg 为 GPL v3 构建。依赖说明见 [THIRD_PARTY.txt](THIRD_PARTY.txt)、[来源与构建记录](SOURCES.md) 和 [licenses](licenses/)。
