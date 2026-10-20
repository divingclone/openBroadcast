# OpenBroadcast Audio

[English](https://github.com/divingclone/openBroadcast/blob/main/README.md) | 简体中文

面向 Windows、macOS 和 Linux 的 NVIDIA Broadcast 独立移植项目，提供麦克风与扬声器降噪、房间回声消除及音频文件处理。
不包含视频、音棚音效或虚拟声卡驱动。macOS 和 Linux 的真实音频硬件验证仍在进行中。

## 安装

**Windows 便携版**：[下载 ZIP](https://github.com/divingclone/openBroadcast/releases/latest/download/OpenBroadcast-windows-x64.zip)，解压后运行 `OpenBroadcast.exe`，保留整个目录。无需安装 Python、NVIDIA Broadcast 或 CUDA。

**Python 安装包（三系统通用）**：[下载 wheel](https://github.com/divingclone/openBroadcast/releases/download/v0.2.3/openbroadcast-0.2.3-py3-none-any.whl)。需要 64 位 Python 3.11+（含 Tkinter），推荐 Python 3.12。
创建并激活虚拟环境：

```sh
python -m venv .venv
```

- Windows PowerShell：`.venv\Scripts\Activate.ps1`
- macOS / Linux：`source .venv/bin/activate`（上一步按需使用 `python3`）

在下载文件所在目录安装并启动：

```sh
python -m pip install --upgrade ./openbroadcast-0.2.3-py3-none-any.whl
openbroadcast-gui
```

以后激活同一环境，在任意目录运行 `openbroadcast-gui` 即可。安装包已包含音频模型。
也可安装 Git 后执行 `python -m pip install "git+https://github.com/divingclone/openBroadcast.git"`，直接从源码安装。

- **Windows**：标准 Python 安装程序包含 Tk；GPU 处理使用 DirectML，需要兼容 DirectX 12 的显卡。
- **macOS**：使用带 Tk 的 Python，并为启动程序的应用授予麦克风权限。pip 不会生成 `.app` 或启动台入口，使用上述命令启动。
- **Linux**：需安装 Tk、PortAudio 及[安装说明](https://github.com/divingclone/openBroadcast/blob/main/docs/compatibility.md#安装与构建)中的桌面依赖。GUI 需要图形桌面。

## 通话接线

Windows / macOS 需另行安装 [VB-CABLE](https://vb-audio.com/Cable/)，完成后刷新设备。Linux 使用 PipeWire 或 PulseAudio 自行配置虚拟音频路由。

| 路由 | OpenBroadcast 输入 | OpenBroadcast 输出 | 通话软件 |
| --- | --- | --- | --- |
| 麦克风 | 真实麦克风 | 虚拟线 A 播放端 | 麦克风：虚拟线 A 录音端 |
| 扬声器 | 虚拟线 B 录音端 | 真实耳机 / 音箱 | 扬声器：虚拟线 B 播放端 |

在 OpenBroadcast 中启用对应路由。单独处理一路只需一条虚拟线；**同时处理两路必须使用两条独立虚拟线**。
Windows 的播放端名为 `CABLE Input`，录音端名为 `CABLE Output`。macOS 两个方向可能同名，请按用途选择。
监听麦克风时使用耳机，避免啸叫。

## 常见问题

- **没有声音**：检查麦克风权限及上述接线；刷新设备并重新选择断开的设备。
- **采样率报错**：实时设备需使用 **48 kHz**，在 Windows 声音设置、macOS“音频 MIDI 设置”或 Linux 音频配置中调整。
- **GPU 报错或卡顿**：在设置中改用 CPU，或减少同时启用的效果和路由。

## 命令行

安装后执行：

```sh
openbroadcast devices
openbroadcast process input.flac output.wav --dereverb
openbroadcast --help
```

平台依赖、GPU 支持、开发构建及验证情况见[兼容性与构建说明](https://github.com/divingclone/openBroadcast/blob/main/docs/compatibility.md)。
