"""Bounded, time-based performance detection for a single audio route.

The caller serializes access. Eight 10 ms hops form a measurement, so Studio
Voice's one inference per 80 ms is never compared with a single 10 ms budget.
"""
from collections import deque


class PerformanceMonitor:
    WINDOW_SECONDS = 1.0
    GRACE_SECONDS = 2.0
    REQUIRED_WINDOWS = 3
    SLOW_FACTOR = 1.05
    RECOVER_FACTOR = 0.95
    GLITCHES_PER_WINDOW = 1

    def __init__(self, now):
        self.deadline = now + self.WINDOW_SECONDS
        self.grace_end = now + self.GRACE_SECONDS
        self.history = deque(maxlen=self.REQUIRED_WINDOWS)
        self.compute_ms = self.audio_ms = self.glitches = 0
        self.pending_ms = self.pending_hops = 0
        self.slow_windows = self.glitch_windows = self.healthy_windows = 0
        self.warning = ""

    def _advance(self, now):
        # A suspended machine does not constitute continuous poor performance.
        if now - self.deadline > 8:
            self.__init__(now)
            return
        while now >= self.deadline:
            if self.deadline > self.grace_end:
                self.history.append((self.compute_ms, self.audio_ms))
                ratio = self.compute_ms / self.audio_ms if self.audio_ms else None
                slow = ratio is not None and ratio > self.SLOW_FACTOR
                glitching = self.glitches >= self.GLITCHES_PER_WINDOW
                healthy = (ratio is None or ratio < self.RECOVER_FACTOR) and not self.glitches
                self.slow_windows = self.slow_windows + 1 if slow else 0
                self.glitch_windows = self.glitch_windows + 1 if glitching else 0
                self.healthy_windows = self.healthy_windows + 1 if healthy else 0
                if self.slow_windows >= self.REQUIRED_WINDOWS:
                    self.warning = "processing"
                elif self.glitch_windows >= self.REQUIRED_WINDOWS:
                    self.warning = "dropouts"
                elif self.healthy_windows >= self.REQUIRED_WINDOWS:
                    self.warning = ""
            self.compute_ms = self.audio_ms = self.glitches = 0
            self.deadline += self.WINDOW_SECONDS

    def processed(self, now, elapsed_ms):
        self._advance(now)
        self.pending_ms += elapsed_ms
        self.pending_hops += 1
        if self.pending_hops == 8:
            self.compute_ms += self.pending_ms
            self.audio_ms += 80.0
            self.pending_ms = self.pending_hops = 0

    def glitch(self, now):
        self._advance(now)
        self.glitches += 1

    def snapshot(self, now):
        self._advance(now)
        compute = sum(item[0] for item in self.history)
        audio = sum(item[1] for item in self.history)
        factor = compute / audio if audio else 0.0
        return dict(process_ms=factor * 10.0, realtime_factor=factor,
                    performance_ready=bool(audio), performance_warning=self.warning)
