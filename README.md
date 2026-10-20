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

GPU processing on Windows requires a DirectX 12-compatible NVIDIA, AMD, or Intel GPU with working drivers.

## Using processed audio in calls

On Windows, install [VB-CABLE Virtual Audio Cable](https://vb-audio.com/Cable/) as administrator, restart your computer, then click Refresh devices.
The driver is not bundled. On Linux, use PipeWire virtual devices; on macOS, use BlackHole.

`CABLE Input` is the playback endpoint, and `CABLE Output` is the recording endpoint of the same virtual cable.

### Processing your microphone

Set OpenBroadcast's microphone input to your physical microphone and **Audio routing → Send to** to **CABLE Input**.
Enable the microphone route. In your calling app, select **CABLE Output** as the microphone and your physical headphones as the speakers.

Use headphones when monitoring your microphone to avoid feedback.

### Processing speaker audio

Set your calling app's speakers to **CABLE Input**. In OpenBroadcast, set **Audio routing → Receive from** to **CABLE Output**,
select your physical headphones or speakers as the output, and enable the speaker route.

With only one virtual cable, stop the microphone route first and switch your calling app's microphone back to the physical device.

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

## Troubleshooting

- **Missing device or no audio**: Check device connections, system microphone permissions, and the routing above. Refresh devices and reselect any disconnected device; the app does not automatically switch to another one.
- **Sample rate error**: Real-time processing requires 48 kHz. In the Windows Sound control panel, select 48000 Hz under the device's Properties → Advanced.
- **GPU initialization fails or audio stutters**: Try switching to CPU processing in Settings, or reduce the number of active effects and routes.

## Command line (source version)

Run these commands from the parent directory containing the `openbroadcast` folder:

```powershell
openbroadcast\.venv\Scripts\python.exe -m openbroadcast devices
openbroadcast\.venv\Scripts\python.exe -m openbroadcast process input.flac output.wav --dereverb
openbroadcast\.venv\Scripts\python.exe -m openbroadcast --help
```
