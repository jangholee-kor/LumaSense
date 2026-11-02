"""Simulation never invokes Twinkle Tray, serial ports or Windows power APIs."""
from .brightness import Monitor


class SimulatedPower:
    def off(self):
        return {"simulated": True, "api": "SC_MONITORPOWER", "value": 2, "accepted": False}
    def wake(self, method, allow_mouse=False):
        return {"simulated": True, "api": method, "accepted": False}


class SimulatedBackend:
    def __init__(self, log):
        self.log = log
        self.value = 40
    def monitors(self):
        return [Monitor("SIMULATED-DISPLAY", "가상 모니터", self.value, "ddcci")]
    def set_brightness(self, identifier, percent):
        if identifier != "SIMULATED-DISPLAY" or type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("잘못된 시뮬레이션 밝기 요청")
        self.value = percent
        return self.log.event("simulated_brightness", monitor_id=identifier, percent=percent, simulated=True)


class SimulatedGuard:
    def __init__(self, *args):
        self.released = False
    def arm(self):
        pass
    def pulse(self):
        pass
    def alive(self):
        return not self.released
    def release(self):
        self.released = True


def sensor_packet(seq, uptime_ms, lux=125, state="stationary", error=False, distance=60):
    present = state != "absent"
    return {"ver": 1, "type": "telemetry", "device": "smart-monitor-s3", "firmware": "simulation",
            "seq": seq, "uptime_ms": uptime_ms, "lux": None if error else lux,
            "light_ok": not error, "radar_ok": not error, "sensor_ok": not error,
            "presence": None if error else present, "moving": None if error else state == "moving",
            "stationary": None if error else state == "stationary", "distance_cm": distance if present and not error else None,
            "errors": ["simulated_sensor_error"] if error else []}
