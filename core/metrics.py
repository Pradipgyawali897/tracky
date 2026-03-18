from __future__ import annotations
import time
import threading
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class StageMetrics:
    fps: float = 0.0
    latency_ms: float = 0.0
    total_frames: int = 0
    drops: int = 0


class Metrics:

    def __init__(self):
        self._lock = threading.Lock()
        self._stages: Dict[str, _Counter] = {}
        self._pipeline_latency: float = 0.0

    def tick(self, stage: str) -> None:
        with self._lock:
            if stage not in self._stages:
                self._stages[stage] = _Counter()
            self._stages[stage].tick()

    def set_latency(self, stage: str, ms: float) -> None:
        with self._lock:
            if stage not in self._stages:
                self._stages[stage] = _Counter()
            self._stages[stage].latency = ms

    def set_drops(self, stage: str, drops: int) -> None:
        with self._lock:
            if stage not in self._stages:
                self._stages[stage] = _Counter()
            self._stages[stage].drops = drops

    def set_pipeline_latency(self, ms: float) -> None:
        with self._lock:
            self._pipeline_latency = ms

    def snapshot(self) -> Dict[str, StageMetrics]:
        with self._lock:
            result = {}
            for name, counter in self._stages.items():
                result[name] = StageMetrics(
                    fps=counter.fps,
                    latency_ms=counter.latency,
                    total_frames=counter.total,
                    drops=counter.drops,
                )
            return result

    @property
    def pipeline_latency_ms(self) -> float:
        with self._lock:
            return self._pipeline_latency

    def summary(self) -> str:
        snap = self.snapshot()
        parts = []
        for name, m in snap.items():
            parts.append(
                f"{name}:{m.fps:.0f}fps/{m.latency_ms:.0f}ms"
            )
        pl = self.pipeline_latency_ms
        parts.append(f"pipe:{pl:.0f}ms")
        return "  ".join(parts)


class _Counter:
    def __init__(self):
        self._count = 0
        self._t0 = time.monotonic()
        self.fps = 0.0
        self.latency = 0.0
        self.total = 0
        self.drops = 0

    def tick(self):
        self._count += 1
        self.total += 1
        now = time.monotonic()
        elapsed = now - self._t0
        if elapsed >= 1.0:
            self.fps = self._count / elapsed
            self._count = 0
            self._t0 = now