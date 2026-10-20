# OpenBroadcast Audio

English | [简体中文](README.zh-CN.md)

Real-time noise reduction and room echo removal for microphones and speakers, with audio file processing.
This project is not an official NVIDIA client. Video features, Studio Voice, and a bundled virtual audio device are not currently supported.

## Getting started

**Windows portable build**: Extract the archive and run `OpenBroadcast.exe`. Keep the entire application folder together.
You do not need to install Python, NVIDIA Broadcast, or CUDA.

**Run from source**: Python 3.10+ with Tkinter is required. Run these commands from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe run_gui.pyw
```

On Linux, also install Tk and PortAudio (for example, `sudo apt install python3-tk libportaudio2`).
On macOS, use a Python installation with Tk support. After installing the dependencies, run `python run_gui.pyw`.
The project is primarily tested on Windows.

Processing uses the CPU by default. You can switch to GPU processing and select a graphics card in Settings (设置).
The Windows version supports DirectX 12-compatible NVIDIA, AMD, and Intel GPUs with working graphics drivers.

## Interface language

The app automatically selects its language at startup. Chinese system languages use Simplified Chinese; all other languages use English.
On Windows, detection uses your Windows display language. On Linux and macOS, it uses the locale environment (`LC_ALL`, `LC_MESSAGES`, then `LANG`), falling back to the system locale.
The interface, tray menu, and built-in user guide follow this selection. Restart the app after changing your system language.

## Using processed audio in calls

On Windows, install [VB-CABLE Virtual Audio Cable](https://vb-audio.com/Cable/) separately:
download and extract it, run the installer for your system architecture as administrator, follow the installation prompts, and restart your computer.
This driver is not included in the portable build. After installation, click Refresh devices (刷新设备) in OpenBroadcast.

`CABLE Input` is the playback endpoint, and `CABLE Output` is the recording endpoint of the same virtual cable.

### Processing your microphone

1. Select your physical microphone in OpenBroadcast's microphone section.
2. Expand Audio routing (音频路由) and set Send to (发送到) to **CABLE Input**.
3. Turn on the effects you need, click an effect name to adjust its strength, then click Enable microphone (启用麦克风).
4. In your calling or recording app, set the microphone to **CABLE Output** and the speakers to your physical headphones.
5. Keep OpenBroadcast running and use your calling app's microphone test to check the audio.

Without a virtual cable, you can set Send to to your headphones for a local test. Avoid monitoring your microphone through speakers, as this can cause feedback.

### Processing speaker audio

If you have only one virtual cable, first stop the microphone route described above and switch your calling app's microphone back to your physical microphone.

1. Set your calling app's speakers to **CABLE Input**.
2. Select your physical headphones or speakers in OpenBroadcast's speaker section.
3. Expand Audio routing (音频路由) and set Receive from (接收来自) to **CABLE Output**.
4. Turn on the effects you need and click Enable speakers (启用扬声器).

### Processing both routes at once

You need two independent virtual cables, such as the separately available VB-CABLE A+B:

| Setting | Device |
| --- | --- |
| OpenBroadcast microphone input | Physical microphone |
| OpenBroadcast microphone Send to | CABLE-A Input |
| Calling app microphone | CABLE-A Output |
| Calling app speakers | CABLE-B Input |
| OpenBroadcast speaker Receive from | CABLE-B Output |
| OpenBroadcast speaker output | Physical headphones or speakers |

The base VB-CABLE package provides only one cable and cannot serve both directions at the same time.
On Linux, you can use PipeWire virtual devices; on macOS, you can use BlackHole.

## Troubleshooting

- **Device not found**: Check that it is connected and enabled in your system, then click Refresh devices. Restart your computer after installing VB-CABLE.
- **No audio in your calling app**: Check that the microphone route is enabled and its level meter is moving. Select devices as described above, and check system microphone permissions and the app's mute settings.
- **No speaker audio**: Check that the speaker route is enabled and its output is set to your physical headphones or speakers.
- **Sample rate error**: Real-time processing requires 48 kHz. In the Windows Sound control panel, select 48000 Hz under the device's Properties → Advanced.
- **GPU initialization fails or audio stutters**: Try switching to CPU processing in Settings, or reduce the number of active effects and routes.
- **Audio does not recover after a device disconnects**: Select a valid device again. The app does not automatically switch to another device.

On Windows, settings are stored in `%APPDATA%\OpenBroadcast\settings.json`.
To remove the portable app, disable launch at startup, exit the app, and delete its folder.
Uninstall VB-CABLE separately using its official installer; first switch your calling app's input and output back to physical devices.

## Command line (source version)

Run these commands from the parent directory containing the `openbroadcast` folder:

```powershell
openbroadcast\.venv\Scripts\python.exe -m openbroadcast devices
openbroadcast\.venv\Scripts\python.exe -m openbroadcast process input.flac output.wav --dereverb
openbroadcast\.venv\Scripts\python.exe -m openbroadcast --help
```

Append `--help` to any subcommand to view its options.
