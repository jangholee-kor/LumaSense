"""Checks recorded physical acceptance, never infers it from API return codes."""
import json
from pathlib import Path


def pending_items(record):
    pending = []
    if record.get("target_model") != "Philips 32M2N8900":
        pending.append("최종 대상 Philips 32M2N8900")
    for key in ("observed_by", "observed_at", "display_mode", "evidence"):
        if not str(record.get(key, "")).strip():
            pending.append(key)
    for level in ("20", "50", "80"):
        if record.get("brightness", {}).get(level) != "pass":
            pending.append(f"밝기 {level}% 실기 관찰")
    if record.get("display_off") != "pass":
        pending.append("화면 절전 실기 관찰")
    if not any(record.get("wake_methods", {}).get(method) == "pass" for method in
               ("monitor_power", "execution_state", "mouse_move")):
        pending.append("한 가지 이상 복귀 방식 실기 관찰")
    return pending


def main():
    path = Path(__file__).resolve().parents[1] / "docs/phase1-validation.json"
    pending = pending_items(json.loads(path.read_text(encoding="utf-8")))
    if pending:
        print("Phase 2 진입 대기: " + ", ".join(pending))
        return 1
    print("기록된 Phase 1 실기 검증 기준 충족. Phase 2 개발을 시작할 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
