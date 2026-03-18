from __future__ import annotations
import threading
import time
import urllib.request
import cv2
import numpy as np

from ..core.types import Frame
from ..core.slot import Slot
from ..core.metrics import Metrics


class CaptureStage:

    def __init__(
        self,
        url: str,
        output: Slot[Frame],
        metrics: Metrics,
        width: int = 640,
        height: int = 480,
        chunk_size: int = 16384,
        reconnect_delay: float = 1.0,
    ):
        self._url = url
        self._output = output
        self._metrics = metrics
        self._width = width
        self._height = height
        self._chunk = chunk_size
        self._reconnect = reconnect_delay

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._sequence = 0
        self.alive = False
        self.reconnects = 0

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="capture"
        )

    def start(self) -> None:
        self._thread.start()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.alive = False
                stream = urllib.request.urlopen(
                    self._url, timeout=10
                )
                buf = b""

                while not self._stop.is_set():
                    data = stream.read(self._chunk)
                    if not data:
                        break

                    buf += data
                    buf = self._extract_frames(buf)

            except Exception:
                self.alive = False
                self.reconnects += 1

            if not self._stop.is_set():
                time.sleep(self._reconnect)

    def _extract_frames(self, buf: bytes) -> bytes:
        while True:
            jpeg_start = buf.find(b"\xff\xd8")
            if jpeg_start < 0:
                return buf[-2:] if len(buf) > 2 else buf

            jpeg_end = buf.find(b"\xff\xd9", jpeg_start + 2)
            if jpeg_end < 0:
                return buf[jpeg_start:]

            jpg_bytes = buf[jpeg_start:jpeg_end + 2]
            buf = buf[jpeg_end + 2:]

            arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)

            if image is None:
                continue

            image = cv2.resize(
                image,
                (self._width, self._height),
                interpolation=cv2.INTER_LINEAR,
            )

            self._sequence += 1
            frame = Frame(
                image=image,
                timestamp=time.monotonic(),
                sequence=self._sequence,
            )

            self._output.put(frame)
            self._metrics.tick("capture")
            self.alive = True

            if not self._ready.is_set():
                self._ready.set()

        return buf