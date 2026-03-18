from __future__ import annotations
import threading
import time

import paho.mqtt.client as mqtt

from ..core.types import Command
from ..core.slot import Slot
from ..core.metrics import Metrics


class CommunicatorStage:

    def __init__(
        self,
        input_slot: Slot[Command],
        metrics: Metrics,
        broker: str = "localhost",
        port: int = 1883,
        topic: str = "robot/cmd",
        client_id: str = "tracker",
        heartbeat: float = 0.15,
        qos: int = 0,
    ):
        self._input = input_slot
        self._metrics = metrics
        self._topic = topic
        self._heartbeat = heartbeat
        self._qos = qos

        self._last_cmd: str | None = None
        self._last_time = 0.0
        self._stop = threading.Event()
        self.connected = False
        self._cmd_count = 0

        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2
            )
        except (AttributeError, TypeError):
            self._client = mqtt.Client()

        self._client.reconnect_delay_set(1, 8)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.connect_async(broker, port, keepalive=10)
        self._client.loop_start()

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="communicator"
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._send("S")
        time.sleep(0.05)
        self._client.loop_stop()
        self._client.disconnect()
        self._thread.join(timeout=5)

    def _on_connect(self, *args) -> None:
        self.connected = True

    def _on_disconnect(self, *args) -> None:
        self.connected = False

    def _send(self, cmd: str) -> None:
        now = time.monotonic()
        if (cmd == self._last_cmd and
                (now - self._last_time) < self._heartbeat):
            return

        self._client.publish(
            self._topic, cmd, qos=self._qos
        )
        self._last_cmd = cmd
        self._last_time = now
        self._cmd_count += 1
        self._metrics.tick("mqtt")

    def _run(self) -> None:
        while not self._stop.is_set():
            cmd = self._input.take()

            if cmd is None:
                time.sleep(0.001)
                continue

            self._send(cmd.serialize())
            self._metrics.set_latency(
                "pipeline", cmd.pipeline_latency_ms
            )