from __future__ import annotations
import time


class PIDController:

    _kp: float
    _ki: float
    _kd: float
    _out_min: float
    _out_max: float
    _i_limit: float
    _d_alpha: float
    _integral: float
    _prev_error: float
    _filtered_derivative: float
    _prev_time: float | None

    __slots__ = (
        "_kp", "_ki", "_kd",
        "_out_min", "_out_max",
        "_i_limit", "_d_alpha",
        "_integral", "_prev_error",
        "_filtered_derivative", "_prev_time",
    )

    def __init__(
        self,
        kp: float = 0.70,
        ki: float = 0.05,
        kd: float = 0.20,
        output_min: float = -1.0,
        output_max: float = 1.0,
        integral_limit: float = 0.40,
        derivative_alpha: float = 0.30,
    ):
        self._kp = kp
        self._ki = ki
        self._kd = kd
        self._out_min = output_min
        self._out_max = output_max
        self._i_limit = integral_limit
        self._d_alpha = derivative_alpha
        self._integral = 0.0
        self._prev_error = 0.0
        self._filtered_derivative = 0.0
        self._prev_time = None
        self.reset()

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = 0.0
        self._filtered_derivative = 0.0
        self._prev_time = None

    def update(self, error: float) -> float:
        now = time.monotonic()
        prev = self._prev_time
        dt = max(now - prev, 1e-4) if prev is not None else 0.033
        self._prev_time = now

        proportional = self._kp * error

        self._integral += error * dt
        self._integral = max(-self._i_limit,
                             min(self._i_limit, self._integral))
        integral = self._ki * self._integral

        raw_derivative = (error - self._prev_error) / dt
        self._filtered_derivative += self._d_alpha * (
            raw_derivative - self._filtered_derivative
        )
        derivative = self._kd * self._filtered_derivative
        self._prev_error = error

        output = proportional + integral + derivative
        return max(self._out_min, min(self._out_max, output))

    @staticmethod
    def steering_to_command(steering: float, dead_zone: float) -> str:
        if abs(steering) < dead_zone:
            return "F"
        return "L" if steering < 0 else "R"