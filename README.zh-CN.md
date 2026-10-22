# OpenBroadcast Audio

[English](https://github.com/divingclone/openBroadcast/blob/main/README.md) | 简体中文

面向 Windows、macOS 和 Linux 的 NVIDIA Broadcast 独立移植项目，提供麦克风与扬声器降噪、房间回声消除及音频文件处理。
不包含视频或虚拟声卡驱动。macOS 和 Linux 的真实音频硬件验证仍在进行中。

## 安装

**Windows 便携版**：[下载 ZIP](https://github.com/divingclone/openBroadcast/releases/latest/download/OpenBroadcast-windows-x64.zip)，解压后运行 `OpenBroadcast.exe`，保留整个目录。无需安装 Python、NVIDIA Broadcast 或 CUDA。

**uv（三系统通用）**：安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后安装并启动：

```sh
uv tool install --python 3.12 "https://github.com/divingclone/openBroadcast/releases/download/v0.2.4/openbroadcast-0.2.4-py3-none-any.whl"
openbroadcast-gui
```

uv 自动管理 Python 和运行环境。以后直接运行 `openbroadcast-gui`；若提示找不到命令，执行 `uv tool update-shell` 后重新打开终端。

也可使用普通 pip 安装，需要 64 位 Python 3.11+（含 Tkinter，推荐 3.12）：

```sh
python -m pip install "https://github.com/divingclone/openBroadcast/releases/download/v0.2.4/openbroadcast-0.2.4-py3-none-any.whl"
```

安装包已包含音频模型。macOS 需为启动程序的应用授予麦克风权限；Linux 需要图形桌面及[系统依赖](https://github.com/divingclone/openBroadcast/blob/main/docs/compatibility.md#安装与构建)。

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
