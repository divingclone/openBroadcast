"""Independent, interruptible preview playback; never uses sounddevice.play()."""
from __future__ import annotations

from ..i18n import tr

import threading
from contextlib import ExitStack
import numpy as np
from .denoiser import RATE
from .com import audio_thread


class PreviewPlayer:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self.position = 0
        self.total = 0
        self.error = ""
        self.active = False

    def play(self, audio, device):
        if self.busy:
            raise RuntimeError(tr('请先停止当前试听。'))
        data = np.asarray(audio, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if data.ndim != 2 or not data.shape[0] or not data.shape[1] or not np.isfinite(data).all():
            raise ValueError(tr('没有可播放的音频。'))
        data = data.copy()
        self.position, self.total, self.error = 0, len(data), ""
        self._stop.clear()
        self.active = True

        def run():
            thread_resources = ExitStack()
            try:
                thread_resources.enter_context(audio_thread())
                import sounddevice as sd
                maximum = int(sd.query_devices(device)["max_output_channels"])
                if maximum < 1:
                    raise ValueError(tr('请选择可播放音频的设备。'))
                # Shared WASAPI speaker endpoints commonly require stereo even
                # for mono recordings. Prefer stereo, then probe the device's
                # native count before falling back to its source count.
                candidates = dict.fromkeys((
                    min(maximum, max(2, data.shape[1])), maximum,
                    min(maximum, data.shape[1]),
                ))
                failure = None
                for channels in candidates:
                    try:
                        sd.check_output_settings(device=device, channels=channels,
                                                 dtype="float32", samplerate=RATE)
                        break
                    except Exception as exc:
                        failure = exc
                else:
                    raise ValueError(tr('此设备不支持 48 kHz 音频试听：{failure}', failure=failure))
                if self._stop.is_set():
                    return
                with sd.OutputStream(samplerate=RATE, channels=channels, dtype="float32",
                                     device=device, blocksize=480) as stream:
                    while self.position < len(data) and not self._stop.is_set():
                        block = data[self.position:self.position + 480]
                        if channels == 1 and data.shape[1] > 1:
                            block = block.mean(axis=1, keepdims=True)
                        elif data.shape[1] == 1 and channels > 1:
                            block = np.repeat(block, channels, axis=1)
                        elif channels > data.shape[1]:
                            block = np.pad(block, ((0, 0), (0, channels-data.shape[1])))
                        stream.write(np.ascontiguousarray(np.clip(block[:, :channels], -1, 1)))
                        self.position += len(block)
            except Exception as exc:
                self.error = str(exc)
            finally:
                thread_resources.close()
                self.active = False

        self._thread = threading.Thread(target=run, name="audio-preview", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    @property
    def busy(self):
        return bool(self._thread and self._thread.is_alive())
