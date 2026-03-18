from __future__ import annotations
import threading
import time

from ..core.types import DetectionResult, Command
from ..core.slot import Slot
from ..core.pid import PIDController
from ..core.metrics import Metrics


class ControllerStage:

    def __init__(
        self,
        input_slot: Slot[DetectionResult],
        output: Slot[Command],
        metrics: Metrics,
        kp: float = 0.70,
        ki: float = 0.05,
        kd: float = 0.20,
        dead_zone: float = 0.10,
        integral_limit: float = 0.40,
        derivative_alpha: float = 0.30,
        lost_timeout: float = 2.0,
        coast_duration: float = 0.5,
    ):
        self._input = input_slot
        self._output = output
        self._metrics = metrics
        self._dead_zone = dead_zone
        self._lost_timeout = lost_timeout
        self._coast = coast_duration

        self._pid = PIDController(
            kp=kp,
            ki=ki,
            kd=kd,
            integral_limit=integral_limit,
            derivative_alpha=derivative_alpha,
        )

        self._stop = threading.Event()
        self._last_seen = 0.0
        self._last_cmd = "S"
        self._last_steering = 0.0

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="controller"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            result = self._input.take()

            if result is None:
                time.sleep(0.001)
                continue

            t0 = time.monotonic()
            h, w = result.frame.hw
            center_x = w * 0.5

            if result.found:
                best = result.best
                error = (best.cx - center_x) / center_x
                steering = self._pid.update(error)

                direction = PIDController.steering_to_command(
                    steering, self._dead_zone
                )

                self._last_cmd = direction
                self._last_steering = steering
                self._last_seen = t0
                confidence = best.confidence

            else:
                age = t0 - self._last_seen
                steering = self._last_steering

                if age > self._lost_timeout:
                    direction = "S"
                    confidence = 0.0
                    self._pid.reset()
                    self._last_cmd = "S"
                elif age > self._coast:
                    direction = self._last_cmd
                    confidence = 0.0
                else:
                    direction = self._last_cmd
                    confidence = 0.0

            cmd = Command(
                direction=direction,
                steering=steering,
                confidence=confidence,
                source_timestamp=result.frame.timestamp,
            )

            self._output.put(cmd)
            self._metrics.tick("controller")

            latency = (t0 - result.frame.timestamp) * 1000.0
            self._metrics.set_pipeline_latency(latency)