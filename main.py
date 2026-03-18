import signal
import time
import yaml
import sys
from pathlib import Path

from .core import Slot, Metrics
from .core.types import Frame, DetectionResult, Command
from .pipeline import (
    CaptureStage,
    DetectorStage,
    ControllerStage,
    CommunicatorStage,
)
from .display import Visualizer


def load_config(path: str = None) -> dict:
    if path is None:
        # Find config relative to this module
        module_dir = Path(__file__).parent
        path = module_dir / "config.yaml"

    with open(path, "r") as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    cam_cfg  = cfg["camera"]
    det_cfg  = cfg["detector"]
    pid_cfg  = cfg["pid"]
    mqtt_cfg = cfg["mqtt"]
    ctl_cfg  = cfg["control"]
    dsp_cfg  = cfg["display"]
    log_cfg  = cfg["logging"]

    metrics = Metrics()

    slot_frames: Slot[Frame] = Slot("frames")
    slot_detections: Slot[DetectionResult] = Slot("detections")
    slot_commands: Slot[Command] = Slot("commands")

    capture: CaptureStage = CaptureStage(
        url=cam_cfg["url"],
        output=slot_frames,
        metrics=metrics,
        width=cam_cfg["width"],
        height=cam_cfg["height"],
        chunk_size=cam_cfg["read_chunk"],
        reconnect_delay=cam_cfg["reconnect_delay"],
    )

    detector: DetectorStage = DetectorStage(
        input_slot=slot_frames,
        output=slot_detections,
        metrics=metrics,
        weights=det_cfg["weights"],
        imgsz=det_cfg["imgsz"],
        confidence=det_cfg["confidence"],
        target_class=det_cfg["target_class"],
        tracker=det_cfg["tracker"],
        device=det_cfg["device"],
        half=det_cfg["half_precision"],
        warmup=det_cfg["warmup_passes"],
    )

    controller: ControllerStage = ControllerStage(
        input_slot=slot_detections,
        output=slot_commands,
        metrics=metrics,
        kp=pid_cfg["kp"],
        ki=pid_cfg["ki"],
        kd=pid_cfg["kd"],
        dead_zone=pid_cfg["dead_zone"],
        integral_limit=pid_cfg["integral_limit"],
        derivative_alpha=pid_cfg["derivative_alpha"],
        lost_timeout=ctl_cfg["lost_timeout"],
        coast_duration=ctl_cfg["coast_duration"],
    )

    communicator: CommunicatorStage = CommunicatorStage(
        input_slot=slot_commands,
        metrics=metrics,
        broker=mqtt_cfg["broker"],
        port=mqtt_cfg["port"],
        topic=mqtt_cfg["topic_cmd"],
        client_id=mqtt_cfg["client_id"],
        heartbeat=mqtt_cfg["heartbeat"],
        qos=mqtt_cfg["qos"],
    )

    visualizer: Visualizer | None = (
        Visualizer(dsp_cfg["window_name"])
        if dsp_cfg["enabled"]
        else None
    )

    print("=" * 60)
    print("  ROBOTRACK PIPELINE")
    print("=" * 60)
    print(f"  Camera    : {cam_cfg['url']}")
    print(f"  Model     : {det_cfg['weights']}")
    print(f"  MQTT      : {mqtt_cfg['broker']}:{mqtt_cfg['port']}")
    print(f"  Display   : {dsp_cfg['enabled']}")
    print("=" * 60)

    capture.start()
    print("[1/4] Capture stage started")

    if not capture.wait_ready(15):
        print("FATAL: no frames from camera")
        sys.exit(1)
    print("[1/4] First frame received")

    detector.start()
    print("[2/4] Detector stage started")

    if not detector.wait_ready(60):
        print("FATAL: YOLO init failed")
        sys.exit(1)
    print("[2/4] YOLO ready")

    controller.start()
    print("[3/4] Controller stage started")

    communicator.start()
    print("[4/4] Communicator stage started")

    print("=" * 60)
    print("  ALL STAGES RUNNING — press q to quit")
    print("=" * 60)

    shutdown = False

    def handle_signal(*_):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGINT, handle_signal)

    last_result = None
    last_command = Command("S", 0.0, 0.0, time.monotonic())
    log_time = time.monotonic()
    log_interval = log_cfg["metrics_interval"]

    try:
        while not shutdown:
            result = slot_detections.get()
            if result is not None:
                last_result = result

            cmd = slot_commands.get()
            if cmd is not None:
                last_command = cmd

            now = time.monotonic()
            if now - log_time >= log_interval:
                print(f"[METRICS] {metrics.summary()}")
                print(
                    f"  Slots: {slot_frames} | "
                    f"{slot_detections} | "
                    f"{slot_commands}"
                )
                log_time = now

            if visualizer and last_result:
                vis = visualizer.render(
                    result=last_result,
                    command=last_command,
                    metrics=metrics,
                    dead_zone=pid_cfg["dead_zone"],
                    cam_alive=capture.alive,
                    mqtt_connected=communicator.connected,
                )

                if visualizer.show(vis):
                    break
            else:
                time.sleep(0.005)

    finally:
        print("\nShutting down pipeline ...")

        communicator.stop()
        print("  [4/4] Communicator stopped")

        controller.stop()
        print("  [3/4] Controller stopped")

        detector.stop()
        print("  [2/4] Detector stopped")

        capture.stop()
        print("  [1/4] Capture stopped")

        if visualizer:
            visualizer.close()

        print("=" * 60)
        snap = metrics.snapshot()
        for name, m in snap.items():
            print(
                f"  {name:12s}: "
                f"{m.total_frames:6d} frames  "
                f"{m.fps:5.1f} fps  "
                f"{m.drops:4d} drops"
            )
        print("=" * 60)
        print("  SHUTDOWN COMPLETE")


if __name__ == "__main__":
    main()