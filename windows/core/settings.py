import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Settings:
    twinkle_path: str = ""
    monitor_id: str = ""
    wake_method: str = "monitor_power"
    recovery_seconds: int = 10
    allow_mouse: bool = False
    fallback_seconds: int = 30

    @classmethod
    def load(cls, path: Path):
        if not path.exists():
            return cls()
        values = json.loads(path.read_text(encoding="utf-8"))
        result = cls(**values)
        if result.wake_method not in ("monitor_power", "execution_state", "mouse_move"):
            raise ValueError("지원하지 않는 복귀 방식")
        if type(result.recovery_seconds) is not int or not 5 <= result.recovery_seconds <= 30:
            raise ValueError("복귀 지연은 5~30초")
        if type(result.fallback_seconds) is not int or not 5 <= result.fallback_seconds <= 60:
            raise ValueError("추가 복귀 간격은 5~60초")
        if type(result.allow_mouse) is not bool or not isinstance(result.twinkle_path, str) or not isinstance(result.monitor_id, str):
            raise ValueError("설정 형식 오류")
        return result

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
