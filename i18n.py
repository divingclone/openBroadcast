"""Small, shared translation catalog for the UI and audio workers.

Select the language once per process so worker messages and tray menus agree.
Windows uses the user's UI language, independently of regional number formats.
Other platforms use the desktop's locale environment, with a locale fallback.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import locale
import os
import sys


def _windows_ui_language() -> str | None:
    try:
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(language_id)
    except (AttributeError, OSError):
        return None


def detect_language() -> str:
    candidate = _windows_ui_language() if sys.platform == "win32" else None
    if not candidate:
        candidate = next((os.environ[name] for name in
                          ("LC_ALL", "LC_MESSAGES", "LANG") if os.environ.get(name)), None)
    if not candidate:
        try:
            candidate = locale.getlocale()[0]
        except (ValueError, TypeError, locale.Error):
            candidate = None
    language = (candidate or "en").split(".")[0].replace("-", "_").split("_")[0].lower()
    return "zh-CN" if language == "zh" else "en"


@lru_cache(maxsize=1)
def get_language() -> str:
    return detect_language()


def tr(message: str, **values) -> str:
    """Translate a source message, then format values without translating data."""
    catalog = ENGLISH if get_language() == "en" else CHINESE
    translated = catalog.get(message, message)
    return translated.format(**values) if values else translated


def readme_filename() -> str:
    return "README.zh-CN.md" if get_language() == "zh-CN" else "README.md"


# Chinese source messages remain stable keys; formatted data is never a lookup key.
ENGLISH = {
    "选择音频文件，应用麦克风效果设置。": "Choose an audio file to apply the microphone effects.",
    "就绪 · 仅音频": "Ready · Audio only",
    "音频": "Audio",
    "文件": "Files",
    "设置": "Settings",
    "仅音频": "Audio only",
    "麦克风": "Microphone",
    "扬声器": "Speakers",
    "刷新设备": "Refresh devices",
    "{title}效果": "{title} effects",
    "噪音消除": "Noise removal",
    "降低背景噪音": "Reduce background noise",
    "降低在扬声器上播放音频的背景噪音": "Reduce background noise in speaker audio",
    "房间回声消除": "Room echo removal",
    "降低混响音效": "Reduce reverberation",
    "降低在扬声器上播放音频的混响声音": "Reduce reverberation in speaker audio",
    "›  音棚音效": "›  Studio Voice",
    "提升音质，模拟高端录音室效果": "Enhance voice quality with a studio sound",
    "尚未移植 · 当前项目未包含音棚音效模型": "Unavailable · Studio Voice model not included",
    "音频路由": "Audio routing",
    "发送到（虚拟声卡 / 监听设备）": "Send to (virtual cable / monitoring device)",
    "接收来自（虚拟声卡录音端）": "Receive from (virtual cable recording endpoint)",
    "将会议或播放器的输出设为虚拟声卡播放端。": "Set your calling app or player's output to the virtual cable playback endpoint.",
    "启用麦克风": "Enable microphone",
    "启用扬声器": "Enable speakers",
    "未启用": "Disabled",
    "强度": "Strength",
    "{title}输出": "{title} output",
    "测试{title}效果": "Test {title} effects",
    "录制一个样本，对比输入音频与处理后的输出音频。": "Record a sample to compare the original and processed audio.",
    "播放样本，了解音频处理如何减少噪音与混响。": "Play a sample to hear how processing reduces noise and echo.",
    "导入音频…": "Import audio…",
    "应用效果": "Apply effects",
    "录制当前扬声器音频": "Record current speaker audio",
    "录制语音": "Record voice",
    "录制音频": "Record audio",
    "输入音频": "Input audio",
    "输出音频": "Output audio",
    "保存录制的音频样本": "Save recorded audio sample",
    "试听设备": "Preview device",
    "停止试听": "Stop preview",
    "正在刷新设备，完成后自动恢复音频…": "Refreshing devices; audio will resume automatically…",
    "音频设备": "Audio devices",
    "存在同名设备，请重新选择": "Duplicate device names; select again",
    "设备不可用：": "Device unavailable: ",
    "没有已启用且已连接的设备": "No enabled, connected devices",
    "请选择设备": "Select a device",
    "请先选择输入设备。": "Select an input device first.",
    "请先选择输出设备。": "Select an output device first.",
    "请先选择试听设备。": "Select a preview device first.",
    "设置保存失败：": "Could not save settings: ",
    "设置保存失败": "Could not save settings",
    "同一虚拟声卡的两端不能互相连接，会形成音频回路。": "Do not connect both ends of the same virtual cable to each other; this creates an audio feedback loop.",
    "无法启动音频": "Could not start audio",
    "录音测试": "Recording test",
    "正在试听 · Esc 停止": "Previewing · Esc to stop",
    "试听": "Preview",
    "WAV 音频": "WAV audio",
    "录音已保存：": "Recording saved: ",
    "保存录音": "Save recording",
    "未找到本机 Broadcast 样本，请导入试听文件。": "No local Broadcast samples found. Import an audio file to preview.",
    "试听样本": "Preview sample",
    "正在处理试听样本…": "Processing preview sample…",
    "试听文件需为 48 kHz；可先在文件页转换。": "Preview files must be 48 kHz. Convert them in the Files tab first.",
    "音频文件处理": "Audio file processing",
    "使用音频页中的麦克风效果与各自强度，保留声道并导出 48 kHz 音频。": "Apply microphone effects and strengths from the Audio tab. Keep the original channels and export at 48 kHz.",
    "输入文件": "Input file",
    "输出文件": "Output file",
    "浏览…": "Browse…",
    "调整音频效果": "Adjust audio effects",
    "开始处理": "Start processing",
    "取消": "Cancel",
    "支持 WAV / FLAC / OGG 输入，WAV / FLAC 输出。\n视频功能尚未实现。": "WAV / FLAC / OGG input; WAV / FLAC output.\nVideo features are not implemented.",
    "FLAC 音频": "FLAC audio",
    "音频文件": "Audio files",
    "设置已更改，正在按新设置重新处理…": "Settings changed; restarting processing with the new settings…",
    "请选择输入文件和输出位置。": "Choose an input file and an output location.",
    "替换输出文件": "Replace output file",
    "是否替换已有文件？\n{dst}": "Replace the existing file?\n{dst}",
    "推理设备": "Processing device",
    "正在载入模型…": "Loading models…",
    "版本 {__version__}  ·  Tkinter / ONNX Runtime": "Version {__version__}  ·  Tkinter / ONNX Runtime",
    "参考本机 NVIDIA Broadcast 2.3.0 的音频界面。\n独立移植项目，仅实现音频；视频功能尚未实现。": "Audio interface inspired by NVIDIA Broadcast 2.3.0.\nIndependent implementation with audio features only; video is not implemented.",
    "音频处理": "Audio processing",
    "设置自动应用于正在运行的音频；切换设备时可能短暂中断。": "Settings apply to active audio automatically. Switching devices may briefly interrupt audio.",
    "CPU 处理器": "CPU",
    "GPU 显卡": "GPU",
    "CPU 线程": "CPU threads",
    "推理显卡": "Processing GPU",
    "显卡已变更：": "GPU changed: ",
    "请选择显卡": "Select a GPU",
    "未检测到可选择的显卡": "No selectable GPUs detected",
    "外观": "Appearance",
    "显示实时处理性能": "Show real-time processing performance",
    "主题": "Theme",
    "深色": "Dark",
    "浅色": "Light",
    "音频连接": "Audio connections",
    "麦克风：真实麦克风 → OpenBroadcast → 虚拟声卡播放端 → 通话软件。\n扬声器：通话软件 → 另一条虚拟声卡 → OpenBroadcast → 耳机。\n\n两路同时使用时，请用不同的虚拟声卡，避免循环。程序不安装虚拟驱动。\n音棚音效模型尚未移植，界面中已禁用该项。降噪与去混响可独立使用。\n\n快捷键：Ctrl+1 音频 · Ctrl+2 文件 · Ctrl+3 设置 · Esc 停止试听。\n设备与强度自动保存；启动程序时自动恢复上次启用的音频路由。":
        "Microphone: physical mic → OpenBroadcast → virtual cable playback endpoint → calling app.\nSpeakers: calling app → a second virtual cable → OpenBroadcast → headphones.\n\nUse separate virtual cables for both routes to avoid feedback. The app does not install virtual drivers.\nStudio Voice is unavailable. Noise removal and echo removal can be used independently.\n\nShortcuts: Ctrl+1 Audio · Ctrl+2 Files · Ctrl+3 Settings · Esc Stop preview.\nDevices and strengths are saved automatically. Previously enabled routes resume on startup.",
    "打开使用说明": "Open user guide",
    "后台运行": "Background operation",
    "开机自启（登录 Windows 后）": "Launch at startup (after Windows sign-in)",
    "登录后进入托盘，并恢复上次启用的音频路由。\n移动便携目录后，请关闭再开启此选项以更新路径。": "Start in the tray after sign-in and restore previously enabled audio routes.\nAfter moving the portable folder, turn this option off and on to update the path.",
    "Windows：关闭主窗口会隐藏到右下角系统托盘，音频处理继续运行。\n点击托盘图标可恢复窗口；右键选择“退出 OpenBroadcast”可完全退出。\n标题栏的最小化按钮仍最小化到任务栏。": "On Windows, closing the window hides it to the system tray while audio processing continues.\nClick the tray icon to restore the window; right-click and choose Exit OpenBroadcast to quit.\nThe title bar's minimize button still minimizes to the taskbar.",
    "退出 OpenBroadcast": "Exit OpenBroadcast",
    "使用 CPU 处理音频，已选显卡不会参与推理。": "Process audio on the CPU. The selected GPU is not used.",
    "使用所选显卡处理音频；切换后自动重新载入模型，无需重启程序。": "Process audio on the selected GPU. Models reload automatically after switching; no restart is needed.",
    "已检测到显卡，但当前运行库不支持该 GPU 后端。\n请按使用说明安装 GPU 运行库并重启，或切换到 CPU。": "A GPU was detected, but this runtime does not support its backend.\nInstall the GPU runtime as described in the guide and restart, or switch to CPU.",
    "请重新选择显卡；若列表为空，请检查驱动及 GPU 运行库。": "Select a GPU again. If the list is empty, check your drivers and GPU runtime.",
    "开机自启": "Launch at startup",
    "OpenBroadcast 使用说明": "OpenBroadcast user guide",
    "系统托盘不可用": "System tray unavailable",
    "窗口已保留，音频处理继续运行。\n{payload}\n\n可使用标题栏最小化，或在设置页选择“退出 OpenBroadcast”。": "The window remains open and audio processing continues.\n{payload}\n\nMinimize using the title bar, or choose Exit OpenBroadcast in Settings.",
    "正在处理… {value0:.0%}": "Processing… {value0:.0%}",
    "已完成：": "Completed: ",
    "已取消，目标文件保持不变。": "Cancelled. The destination file is unchanged.",
    "处理失败：": "Processing failed: ",
    "试听已取消": "Preview cancelled",
    "取消切换": "Cancel switch",
    "停止加载": "Stop loading",
    "停止": "Stop",
    "正在停止…": "Stopping…",
    "正在载入模型与打开音频设备…": "Loading models and opening audio devices…",
    "正在释放音频设备…": "Releasing audio devices…",
    "错误：": "Error: ",
    "正在应用新设置，完成后自动恢复…": "Applying new settings; audio will resume automatically…",
    "无法恢复音频：": "Could not resume audio: ",
    "运行中 · {value0} 声道 · 模型延迟 {value1:.0f} ms + 缓冲": "Running · {value0} channels · Model latency {value1:.0f} ms + buffer",
    "\n处理 {value0:.1f} ms / 10 ms · 丢帧 {value1} · 欠载 {value2}": "\nProcessing {value0:.1f} ms / 10 ms · Dropped {value1} · Underruns {value2}",
    "试听失败：": "Preview failed: ",
    "试听 {value0:.1f} / {value1:.1f} 秒 · Esc 停止": "Preview {value0:.1f} / {value1:.1f} s · Esc to stop",
    "运行中": " running",
    " · 每 10 ms 处理耗时 {total_ms:.1f} ms": " · {total_ms:.1f} ms processing per 10 ms",
    "就绪 · 仅音频 · 视频功能尚未实现": "Ready · Audio only · Video not implemented",
    "当前效果：噪音消除 {value0} ({value1:.0%})  ·  房间回声消除 {value2} ({value3:.0%})": "Effects: Noise removal {value0} ({value1:.0%})  ·  Echo removal {value2} ({value3:.0%})",
    "开启": "On",
    "关闭": "Off",
    "正在停止音频并释放资源…": "Stopping audio and releasing resources…",
    "OpenBroadcast · 音频处理": "OpenBroadcast · Audio processing",
    "打开 OpenBroadcast": "Open OpenBroadcast",
    "系统托盘已停止。": "The system tray has stopped.",
    "找不到 pythonw.exe，请使用 Windows Python 或便携版。": "pythonw.exe was not found. Use Windows Python or the portable build.",
    "程序路径过长，无法注册开机自启；请移到更短的目录。": "The application path is too long for startup registration. Move it to a shorter path.",
    "开机自启目前仅支持 Windows。": "Launch at startup is currently supported only on Windows.",
    "启动失败：{exc}\n\n请使用安装了 requirements.txt 的 Python。\n推荐：.venv\\Scripts\\pythonw.exe run_gui.pyw": "Startup failed: {exc}\n\nUse a Python environment with requirements.txt installed.\nRecommended: .venv\\Scripts\\pythonw.exe run_gui.pyw",
    "Windows 音频线程初始化失败 (COM 0x{result:08X})": "Windows audio thread initialization failed (COM 0x{result:08X})",
    "所选推理后端初始化失败，请检查 GPU 运行库及驱动，或在设置中切换到 CPU。": "The selected processing backend failed to initialize. Check the GPU runtime and drivers, or switch to CPU in Settings.",
    "（未安装支持）": " (support not installed)",
    "所选显卡不可用或已变更，请到设置中重新选择推理显卡。": "The selected GPU is unavailable or has changed. Select a GPU again in Settings.",
    "{value0} 尚未安装 GPU 推理支持。请切换到 CPU，或按照使用说明安装 GPU 运行库后重启程序。": "GPU processing support is not installed for {value0}. Switch to CPU, or install the GPU runtime as described in the guide and restart.",
    "请先停止当前试听。": "Stop the current preview first.",
    "没有可播放的音频。": "There is no audio to play.",
    "请选择可播放音频的设备。": "Select an audio playback device.",
    "此设备不支持 48 kHz 音频试听：{failure}": "This device does not support 48 kHz audio preview: {failure}",
    "试听样本大小或位置无效。": "The preview sample size or location is invalid.",
    "试听样本已损坏或安装文件已更改。": "The preview sample is damaged or the installation files have changed.",
    "试听样本读取不完整。": "The preview sample could not be read completely.",
    "此样本为 {rate} Hz；请通过文件页转换为 48 kHz。": "This sample is {rate} Hz. Convert it to 48 kHz in the Files tab.",
}

# Messages originating in the audio engine use English source keys.
CHINESE = {
    "Only mono and stereo routes are supported": "仅支持单声道和双声道音频路由。",
    "Select both input and output devices": "请选择输入设备和输出设备。",
    "The route is still running or stopping": "音频路由仍在运行或正在停止。",
    "Recording duration must be between 0 and 20 seconds": "录音时长必须在 0 到 20 秒之间。",
    "Start the audio route before recording": "请先启用音频路由，再开始录音。",
    "A recording is already in progress": "录音已在进行中。",
    "Input device returned {frames} frames; expected {HOP}": "输入设备返回了 {frames} 帧，预期为 {HOP} 帧。",
    "Input device returned non-finite samples": "输入设备返回了无效的音频数值。",
    "Output device requested {frames} frames; expected {HOP}": "输出设备请求了 {frames} 帧，预期为 {HOP} 帧。",
    "Model latency must be a multiple of the hop size": "模型延迟必须是音频处理块大小的整数倍。",
    "An audio device stopped unexpectedly or disconnected": "音频设备意外停止或已断开连接。",
    "The audio model returned non-finite samples": "音频模型返回了无效的音频数值。",
    "Audio file processing was cancelled": "音频文件处理已取消。",
    "Input audio ended before its declared frame count": "输入音频提前结束，未达到声明的帧数。",
    "Input audio contains NaN or infinite samples": "输入音频包含 NaN 或无穷大的数值。",
    "Choose a different output path to preserve the source recording": "请选择不同的输出路径，以保留原始录音。",
    "Output must be a .wav or .flac file": "输出文件必须是 .wav 或 .flac 格式。",
    "Input must be a WAV, FLAC or OGG audio file": "输入文件必须是 WAV、FLAC 或 OGG 格式。",
    "Empty audio cannot be encoded as FLAC; choose WAV output": "空音频无法编码为 FLAC，请选择 WAV 输出。",
    "Use a 16-bit PCM WAV file": "请使用 16-bit PCM WAV 文件。",
    "NVIDIA Broadcast's 48 kHz model requires 48 kHz audio": "NVIDIA Broadcast 的 48 kHz 模型需要 48 kHz 音频。",
    "Expected 480 finite mono samples": "需要 480 个有效的单声道音频采样。",
    "Expected finite mono audio": "需要有效的单声道音频。",
    "Could not save OpenBroadcast settings to {path}: {error}": "无法将 OpenBroadcast 设置保存到 {path}：{error}",
}
