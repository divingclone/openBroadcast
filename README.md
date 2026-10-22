# OpenBroadcast Audio

English | [简体中文](https://github.com/divingclone/openBroadcast/blob/main/README.zh-CN.md)

An independent port of NVIDIA Broadcast for Windows, macOS and Linux, providing microphone and speaker noise reduction, room echo removal, and audio file processing.
Video and virtual audio drivers are not included. macOS and Linux audio hardware validation is still in progress.

## Installation

**Windows portable build**: [Download the ZIP](https://github.com/divingclone/openBroadcast/releases/latest/download/OpenBroadcast-windows-x64.zip), extract it and run `OpenBroadcast.exe`. Keep the entire folder together. Python, NVIDIA Broadcast and CUDA are not required.

**uv (all platforms)**: Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then install and launch:

```sh
uv tool install --python 3.12 "https://github.com/divingclone/openBroadcast/releases/download/v0.2.4/openbroadcast-0.2.4-py3-none-any.whl"
openbroadcast-gui
```

uv manages Python and the environment automatically. For later launches, run `openbroadcast-gui`. If the command is not found, run `uv tool update-shell` and reopen your terminal.

You can also use regular pip with 64-bit Python 3.11+ and Tkinter (3.12 recommended):

```sh
python -m pip install "https://github.com/divingclone/openBroadcast/releases/download/v0.2.4/openbroadcast-0.2.4-py3-none-any.whl"
```

Audio models are included. On macOS, grant microphone permission to the launching app. On Linux, a graphical desktop and [system dependencies](https://github.com/divingclone/openBroadcast/blob/main/docs/compatibility.md#安装与构建) are required.

## Audio routing for calls

Install [VB-CABLE](https://vb-audio.com/Cable/) separately on Windows or macOS, then refresh devices. On Linux, configure virtual routing with PipeWire or PulseAudio.

| Route | OpenBroadcast input | OpenBroadcast output | Calling app |
| --- | --- | --- | --- |
| Microphone | Physical microphone | Virtual cable A playback endpoint | Microphone: cable A recording endpoint |
| Speakers | Virtual cable B recording endpoint | Physical headphones / speakers | Speakers: cable B playback endpoint |

Enable the corresponding route in OpenBroadcast. One virtual cable is enough for either route; **two independent cables are required to use both at once**.
Windows names the playback endpoint `CABLE Input` and the recording endpoint `CABLE Output`. macOS may use the same name for both directions; select by role.
Use headphones when monitoring your microphone to avoid feedback.

## Troubleshooting

- **No audio**: Check microphone permissions and the routing above. Refresh devices and reselect any disconnected device.
- **Sample rate error**: Real-time devices must use **48 kHz**. Set this in Windows Sound settings, macOS Audio MIDI Setup, or your Linux audio configuration.
- **GPU error or stuttering**: Select CPU in Settings, or reduce the number of active effects and routes.

## Command line

After installation:

```sh
openbroadcast devices
openbroadcast process input.flac output.wav --dereverb
openbroadcast --help
```

See the [compatibility and build notes](https://github.com/divingclone/openBroadcast/blob/main/docs/compatibility.md) for platform dependencies, GPU support, development and validation details.
