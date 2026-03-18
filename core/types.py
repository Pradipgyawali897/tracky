from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import time
import numpy as np


@dataclass(slots=True)
class Frame:
    image: np.ndarray
    timestamp: float
    sequence: int

    @property
    def age_ms(self) -> float:
        return (time.monotonic() - self.timestamp) * 1000.0

    @property
    def hw(self) -> tuple[int, int]:
        return self.image.shape[:2]


@dataclass(slots=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    track_id: Optional[int] = None

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) * 0.5

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) * 0.5

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(slots=True)
class DetectionResult:
    frame: Frame
    detections: List[Detection]
    inference_ms: float
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def best(self) -> Optional[Detection]:
        return self.detections[0] if self.detections else None

    @property
    def found(self) -> bool:
        return len(self.detections) > 0


@dataclass(slots=True)
class Command:
    direction: str
    steering: float
    confidence: float
    source_timestamp: float
    command_timestamp: float = field(default_factory=time.monotonic)

    @property
    def pipeline_latency_ms(self) -> float:
        return (self.command_timestamp - self.source_timestamp) * 1000.0

    def serialize(self) -> str:
        return self.direction