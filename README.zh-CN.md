# OpenBroadcast Audio

[English](README.md) | 简体中文

用于麦克风和扬声器的实时降噪、房间回声消除，也可处理音频文件。
本项目不是 NVIDIA 官方客户端；目前不支持视频、音棚音效或自带虚拟音频设备。

## 启动

**Windows 便携版**：解压后运行 `OpenBroadcast.exe`，保留整个程序目录。
无需安装 Python、NVIDIA Broadcast 或 CUDA。

**源码运行**：需要 Python 3.10+（含 Tkinter），在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe run_gui.pyw
```

Linux 还需安装 Tk 和 PortAudio（如 `sudo apt install python3-tk libportaudio2`）；
macOS 需使用带 Tk 的 Python。安装依赖后运行 `python run_gui.pyw`。
项目主要在 Windows 上验证。

Windows GPU 处理需要兼容 DirectX 12 的 NVIDIA、AMD 或 Intel 显卡，并安装正常工作的驱动。

## 将处理后的声音用于通话

Windows 需以管理员身份安装 [VB-CABLE 虚拟音频线](https://vb-audio.com/Cable/)，重启电脑后点击“刷新设备”。
程序不附带此驱动。Linux 可使用 PipeWire 虚拟设备，macOS 可使用 BlackHole。

`CABLE Input` 是播放端，`CABLE Output` 是录音端，两者属于同一条音频线。

### 处理麦克风

在 OpenBroadcast 中选择真实麦克风，将“音频路由 → 发送到”设为 **CABLE Input**，启用麦克风路由。
在通话软件中，将麦克风设为 **CABLE Output**，扬声器设为真实耳机。

监听麦克风时请使用耳机，避免啸叫。

### 处理扬声器

将通话软件的扬声器设为 **CABLE Input**。在 OpenBroadcast 中，将“音频路由 → 接收来自”设为 **CABLE Output**，
输出选择真实耳机或音箱，启用扬声器路由。

只有一条虚拟音频线时，先停止麦克风路由，并将通话软件的麦克风改回真实设备。

### 同时处理两路

需要两条独立的虚拟音频线，例如另行获取的 VB-CABLE A+B：

| 设置位置 | 选择设备 |
| --- | --- |
| OpenBroadcast 麦克风输入 | 真实麦克风 |
| OpenBroadcast 麦克风“发送到” | CABLE-A Input |
| 通话软件的麦克风 | CABLE-A Output |
| 通话软件的扬声器 | CABLE-B Input |
| OpenBroadcast 扬声器“接收来自” | CABLE-B Output |
| OpenBroadcast 扬声器输出 | 真实耳机或音箱 |

## 常见问题

- **找不到设备或没有声音**：检查设备连接、系统麦克风权限及上述接线。刷新设备并重新选择断开的设备；程序不会自动改用其他设备。
- **采样率报错**：实时处理要求 48 kHz，在 Windows 声音控制面板的设备“属性 → 高级”中选择 48000 Hz。
- **GPU 启动失败或音频卡顿**：尝试在“设置”中改用 CPU，或减少同时启用的效果和路由。

## 命令行（源码版）

在包含 `openbroadcast` 文件夹的父目录执行：

```powershell
openbroadcast\.venv\Scripts\python.exe -m openbroadcast devices
openbroadcast\.venv\Scripts\python.exe -m openbroadcast process input.flac output.wav --dereverb
openbroadcast\.venv\Scripts\python.exe -m openbroadcast --help
```
