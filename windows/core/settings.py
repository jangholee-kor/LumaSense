import json
from dataclasses import asdict, dataclass, field
import math
from pathlib import Path


@dataclass
class Settings:
    twinkle_path: str = ""
    monitor_id: str = ""
    wake_method: str = "monitor_power"
    recovery_seconds: int = 10
    allow_mouse: bool = False
    fallback_seconds: int = 30
    serial_port: str = ""
    serial_number: str = ""
    connect_on_start: bool = False
    auto_brightness: bool = False
    auto_presence: bool = False
    curve: list = field(default_factory=lambda: [[0, 10], [5, 15], [30, 25], [100, 40], [300, 60], [500, 75], [1000, 85]])
    brightness_min: int = 10
    brightness_max: int = 85
    transition_seconds: float = 2.0
    ema_alpha: float = 0.6
    brightness_interval: float = 1.0
    brightness_deadband: int = 2
    manual_pause_seconds: int = 900
    absence_seconds: int = 30
    recent_input_seconds: int = 30
    use_recent_input: bool = True
    stabilization_seconds: float = 5.0
    sensor_stale_seconds: float = 3.0
    max_distance_cm: int = 150
    production_wake_method: str = "execution_state"
    start_minimized: bool = False
    login_startup: bool = False
    radar_engineering: bool = False
    radar_apply_range: bool = False
    radar_min_gate: int = 0
    radar_max_gate: int = 1
    radar_absence_seconds: int = 5
    radar_apply_thresholds: bool = False
    radar_moving_thresholds: list = field(default_factory=lambda: [35] * 14)
    radar_stationary_thresholds: list = field(default_factory=lambda: [35] * 14)

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls()
        values = json.loads(path.read_text(encoding="utf-8"))
        result = cls(**values)
        result.validate()
        return result

    def validate(self):
        result = self
        if result.wake_method not in ("monitor_power", "execution_state", "mouse_move"):
            raise ValueError("지원하지 않는 복귀 방식")
        if type(result.recovery_seconds) is not int or not 5 <= result.recovery_seconds <= 30:
            raise ValueError("복귀 지연은 5~30초")
        if type(result.fallback_seconds) is not int or not 5 <= result.fallback_seconds <= 60:
            raise ValueError("추가 복귀 간격은 5~60초")
        if type(result.allow_mouse) is not bool or not isinstance(result.twinkle_path, str) or not isinstance(result.monitor_id, str):
            raise ValueError("설정 형식 오류")
        for name in ("serial_port", "serial_number"):
            if not isinstance(getattr(self, name), str) or len(getattr(self, name)) > 256:
                raise ValueError(f"잘못된 {name}")
        for name in ("connect_on_start", "auto_brightness", "auto_presence", "use_recent_input", "start_minimized", "login_startup",
                     "radar_engineering", "radar_apply_range", "radar_apply_thresholds"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"잘못된 {name}")
        ranges = {"brightness_min": (0, 100), "brightness_max": (0, 100), "brightness_deadband": (1, 20),
                  "manual_pause_seconds": (0, 86400), "absence_seconds": (5, 3600),
                  "recent_input_seconds": (1, 3600), "max_distance_cm": (1, 900),
                  "radar_min_gate": (0, 13), "radar_max_gate": (0, 13), "radar_absence_seconds": (5, 65535)}
        for name, (low, high) in ranges.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name}: {low}~{high} 정수 필요")
        if self.brightness_min > self.brightness_max:
            raise ValueError("최소 밝기는 최대 밝기 이하여야 합니다.")
        if self.radar_min_gate > self.radar_max_gate:
            raise ValueError("레이더 최소 거리문은 최대 거리문 이하여야 합니다.")
        for values in (self.radar_moving_thresholds, self.radar_stationary_thresholds):
            if not isinstance(values, list) or len(values) != 14 or any(type(v) is not int or not 0 <= v <= 100 for v in values):
                raise ValueError("레이더 민감도는 거리문 14개의 0~100 정수 필요")
        for name, low, high in (("transition_seconds", 1, 3), ("ema_alpha", .01, 1), ("brightness_interval", .2, 10),
                                ("stabilization_seconds", 1, 60), ("sensor_stale_seconds", .5, 15)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name}: {low}~{high} 숫자 필요")
        if self.production_wake_method not in ("execution_state", "monitor_power", "mouse_move"):
            raise ValueError("잘못된 자동 복귀 방식")
        if self.production_wake_method == "mouse_move" and not self.allow_mouse:
            raise ValueError("자동 마우스 복귀를 사용하려면 마우스 이동을 허용해야 합니다.")
        if not isinstance(self.curve, list) or not 2 <= len(self.curve) <= 32:
            raise ValueError("조도 곡선은 2~32개 점이 필요합니다.")
        previous = -1
        for point in self.curve:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("곡선의 점은 [lux, 밝기] 형식")
            lux, brightness = point
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                raise ValueError("곡선은 유한한 숫자 필요")
            if not previous < lux <= 65535 or not 0 <= brightness <= 100:
                raise ValueError("조도는 오름차순, 밝기는 0~100")
            previous = lux
        return self

    def save(self, path: Path):
        self.validate()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
