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

默认使用 CPU，可在“设置”中切换至 GPU 并选择显卡。
Windows 版支持兼容 DirectX 12 的 NVIDIA、AMD、Intel 显卡，需安装正常工作的显卡驱动。

## 将处理后的声音用于通话

Windows 需另行安装 [VB-CABLE 虚拟音频线](https://vb-audio.com/Cable/)：
下载并解压，以管理员身份运行适合系统架构的安装程序，按提示安装并重启电脑。
便携包不包含此驱动。安装后在 OpenBroadcast 中点击“刷新设备”。

`CABLE Input` 是播放端，`CABLE Output` 是录音端，两者属于同一条音频线。

### 处理麦克风

1. 在 OpenBroadcast 的麦克风区域选择真实麦克风。
2. 展开“音频路由”，将“发送到”设为 **CABLE Input**。
3. 开启需要的效果，点击效果名称调整强度，再点击“启用麦克风”。
4. 在通话或录制软件中，将麦克风设为 **CABLE Output**，扬声器设为真实耳机。
5. 保持 OpenBroadcast 运行，用通话软件的麦克风测试确认声音正常。

没有虚拟音频线时，可将“发送到”设为耳机进行本地测试；避免用音箱监听麦克风，以免啸叫。

### 处理扬声器

只有一条虚拟音频线时，先停止上述麦克风路由，并将通话软件的麦克风改回真实麦克风。

1. 将通话软件的扬声器设为 **CABLE Input**。
2. 在 OpenBroadcast 的扬声器区域选择真实耳机或音箱。
3. 展开“音频路由”，将“接收来自”设为 **CABLE Output**。
4. 开启需要的效果，点击“启用扬声器”。

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

基础版 VB-CABLE 只有一条线，不能同时用于两个方向。
Linux 可使用 PipeWire 虚拟设备，macOS 可使用 BlackHole。

## 试听与文件处理

- **录音测试**：先启用对应路由，再录制最多 20 秒音频，对比输入与输出；点击保存才会写入 WAV。
- **试听**：在“试听设备”中选择耳机。可导入 48 kHz 音频，最长试听 30 秒；其他采样率可先在“文件”页转换。
- **文件处理**：先在音频页调整麦克风效果与强度，再进入“文件”页选择输入和输出，点击“开始处理”。
  支持 WAV / FLAC / OGG 输入、WAV / FLAC 输出；输出为 48 kHz、16-bit，保留声道数，不能覆盖输入文件。
- 处理过程中修改效果或推理设置会自动重新处理；取消或失败会保留原有输出文件。
  对重采样质量要求较高时，请先用专用音频工具转换为 48 kHz。

## 后台运行

- Windows 下点击窗口 **×** 会隐藏到系统托盘，音频继续运行；点击托盘图标或再次启动程序可恢复窗口。
- 完全退出：右键托盘图标，或在“设置”页选择“退出 OpenBroadcast”。
- 程序会恢复上次启用的音频路由；不希望下次恢复时，先点击该路的“停止”。
- 在“设置 → 后台运行”中开启“开机自启”。移动程序目录后需关闭再开启此选项；删除程序前先关闭自启。
- 非 Windows 系统关闭窗口即退出。

## 常见问题

- **找不到设备**：确认设备已连接、在系统中启用，点击“刷新设备”；VB-CABLE 安装后需重启电脑。
- **通话软件收不到声音**：确认麦克风路由已启用、电平有变化，并按上面的接线选择设备；检查系统麦克风权限及软件静音状态。
- **扬声器无声**：确认扬声器路由已启用，输出为真实耳机或音箱。
- **采样率报错**：实时处理要求 48 kHz，在 Windows 声音控制面板的设备“属性 → 高级”中选择 48000 Hz。
- **GPU 启动失败或音频卡顿**：尝试在“设置”中改用 CPU，或减少同时启用的效果和路由。
- **设备断开后无法恢复**：重新选择有效设备；程序不会自动改用其他设备。

Windows 设置文件位于 `%APPDATA%\OpenBroadcast\settings.json`。
卸载便携版前先关闭自启并退出程序，再删除程序目录；VB-CABLE 需通过其官方安装程序单独卸载，
卸载前将通话软件的输入、输出改回真实设备。

## 命令行（源码版）

在包含 `openbroadcast` 文件夹的父目录执行：

```powershell
openbroadcast\.venv\Scripts\python.exe -m openbroadcast devices
openbroadcast\.venv\Scripts\python.exe -m openbroadcast process input.flac output.wav --dereverb
openbroadcast\.venv\Scripts\python.exe -m openbroadcast --help
```

各子命令可追加 `--help` 查看选项。
