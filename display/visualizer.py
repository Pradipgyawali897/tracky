from __future__ import annotations
import cv2
import numpy as np

from ..core.types import DetectionResult, Command
from ..core.metrics import Metrics


class Visualizer:

    FONT       = cv2.FONT_HERSHEY_SIMPLEX
    GREEN      = (0, 255, 0)
    RED        = (0, 0, 255)
    YELLOW     = (0, 255, 255)
    WHITE      = (255, 255, 255)
    BLACK      = (0, 0, 0)
    GRAY       = (80, 80, 80)
    CYAN       = (255, 255, 0)
    LINE       = cv2.LINE_AA

    def __init__(self, window_name: str = "RoboTrack"):
        self._name = window_name

    def render(
        self,
        result: DetectionResult,
        command: Command,
        metrics: Metrics,
        dead_zone: float,
        cam_alive: bool,
        mqtt_connected: bool,
    ) -> np.ndarray:
        vis = result.frame.image.copy()
        h, w = vis.shape[:2]
        mid = w // 2

        self._draw_deadzone(vis, mid, h, dead_zone)
        self._draw_detections(vis, result, command)
        self._draw_statusbar(
            vis, w, h, command, metrics,
            cam_alive, mqtt_connected, result.inference_ms
        )

        return vis

    def show(self, frame: np.ndarray) -> bool:
        cv2.imshow(self._name, frame)
        return (cv2.waitKey(1) & 0xFF) == ord("q")

    def close(self) -> None:
        cv2.destroyAllWindows()

    def _draw_deadzone(
        self, img: np.ndarray,
        mid: int, h: int, dz: float
    ) -> None:
        offset = int(mid * dz)

        overlay = img.copy()
        cv2.rectangle(
            overlay,
            (mid - offset, 0),
            (mid + offset, h),
            (30, 30, 30),
            -1,
        )
        cv2.addWeighted(overlay, 0.15, img, 0.85, 0, img)

        cv2.line(img, (mid, 0), (mid, h), self.GRAY, 1)
        cv2.line(
            img,
            (mid - offset, 0),
            (mid - offset, h),
            self.YELLOW, 1,
        )
        cv2.line(
            img,
            (mid + offset, 0),
            (mid + offset, h),
            self.YELLOW, 1,
        )

    def _draw_detections(
        self, img: np.ndarray,
        result: DetectionResult,
        command: Command,
    ) -> None:
        for i, det in enumerate(result.detections):
            bx1, by1 = int(det.x1), int(det.y1)
            bx2, by2 = int(det.x2), int(det.y2)

            color = self.GREEN if i == 0 else self.CYAN

            cv2.rectangle(img, (bx1, by1), (bx2, by2), color, 2)

            cv2.circle(
                img,
                (int(det.cx), int(det.cy)),
                4, self.RED, -1,
            )

            tid = f"#{det.track_id}" if det.track_id else ""
            label = (
                f"{command.direction} "
                f"{tid} "
                f"{det.confidence:.2f}"
            )

            (tw, th), _ = cv2.getTextSize(
                label, self.FONT, 0.45, 1
            )
            cv2.rectangle(
                img,
                (bx1, by1 - th - 8),
                (bx1 + tw + 4, by1),
                color,
                -1,
            )
            cv2.putText(
                img, label,
                (bx1 + 2, by1 - 4),
                self.FONT, 0.45, self.BLACK, 1, self.LINE,
            )

    def _draw_statusbar(
        self, img: np.ndarray,
        w: int, h: int,
        command: Command,
        metrics: Metrics,
        cam_alive: bool,
        mqtt_ok: bool,
        infer_ms: float,
    ) -> None:
        bar_h = 32
        bar_y = h - bar_h
        cv2.rectangle(
            img, (0, bar_y), (w, h), self.BLACK, -1
        )

        snap = metrics.snapshot()

        cap_fps = snap.get("capture", None)
        det_fps = snap.get("detector", None)
        ctl_fps = snap.get("controller", None)

        parts = [f"CMD:{command.direction}"]

        if cap_fps:
            parts.append(f"CAM:{cap_fps.fps:.0f}")
        if det_fps:
            parts.append(
                f"YOLO:{det_fps.fps:.0f}/{infer_ms:.0f}ms"
            )
        if ctl_fps:
            parts.append(f"CTL:{ctl_fps.fps:.0f}")

        pl = metrics.pipeline_latency_ms
        parts.append(f"LAT:{pl:.0f}ms")

        text = "  ".join(parts)

        cv2.putText(
            img, text,
            (50, h - 10),
            self.FONT, 0.38, self.WHITE, 1, self.LINE,
        )

        cam_color = self.GREEN if cam_alive else self.RED
        mqtt_color = self.GREEN if mqtt_ok else self.RED

        cv2.circle(img, (12, bar_y + 16), 6, cam_color, -1)
        cv2.circle(img, (30, bar_y + 16), 6, mqtt_color, -1)