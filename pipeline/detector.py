from __future__ import annotations
import threading
import time
import numpy as np

from ..core.types import Frame, Detection, DetectionResult
from ..core.slot import Slot
from ..core.metrics import Metrics


class DetectorStage:

    def __init__(
        self,
        input_slot: Slot[Frame],
        output: Slot[DetectionResult],
        metrics: Metrics,
        weights: str = "yolov8n.pt",
        imgsz: int = 640,
        confidence: float = 0.25,
        target_class: int = 32,
        tracker: str = "botsort.yaml",
        device: int = 0,
        half: bool = True,
        warmup: int = 3,
    ):
        self._input = input_slot
        self._output = output
        self._metrics = metrics
        self._weights = weights
        self._imgsz = imgsz
        self._conf = confidence
        self._target = target_class
        self._tracker = tracker
        self._device = device
        self._half = half
        self._warmup = warmup

        self._stop = threading.Event()
        self._ready = threading.Event()

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="detector"
        )

    def start(self) -> None:
        self._thread.start()

    def wait_ready(self, timeout: float = 60.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        import torch
        torch.backends.cudnn.benchmark = True

        from ultralytics import YOLO

        model = YOLO(self._weights)
        model.to(f"cuda:{self._device}")
        model.fuse()

        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        for _ in range(self._warmup):
            model.predict(
                dummy,
                imgsz=self._imgsz,
                half=self._half,
                verbose=False,
                device=self._device,
            )

        self._ready.set()

        while not self._stop.is_set():
            frame = self._input.get()
            if frame is None:
                time.sleep(0.001)
                continue

            t0 = time.monotonic()

            results = model.track(
                frame.image,
                persist=True,
                classes=[self._target],
                imgsz=self._imgsz,
                conf=self._conf,
                half=self._half,
                verbose=False,
                device=self._device,
                tracker=self._tracker,
            )[0]

            inference_ms = (time.monotonic() - t0) * 1000.0

            detections = []
            for box in results.boxes:
                coords = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                tid = (
                    int(box.id[0]) if box.id is not None else None
                )
                detections.append(Detection(
                    x1=coords[0],
                    y1=coords[1],
                    x2=coords[2],
                    y2=coords[3],
                    confidence=conf,
                    track_id=tid,
                ))

            detections.sort(key=lambda d: d.area, reverse=True)

            result = DetectionResult(
                frame=frame,
                detections=detections,
                inference_ms=inference_ms,
            )

            self._output.put(result)
            self._metrics.tick("detector")
            self._metrics.set_latency("detector", inference_ms)
            self._metrics.set_drops(
                "capture", self._input.drops
            )