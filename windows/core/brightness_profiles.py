"""Named, discrete lux/brightness profiles; no interpolation or output side effects."""
from bisect import bisect_right
from copy import deepcopy
import math


def default_brightness_profiles():
    return [{"name": "기본", "points": [[0, 2], [100, 30], [300, 55]],
             "hysteresis_lux": 0.0, "hold_seconds": 1.0}]


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != {"name", "points", "hysteresis_lux", "hold_seconds"}:
        raise ValueError("밝기 프로필은 이름·구간·하강 이력·유지 시간이 필요합니다.")
    name = profile["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 40 or name != name.strip() or any(ord(c) < 32 for c in name):
        raise ValueError("프로필 이름은 앞뒤 공백 없이 1~40자로 입력하세요.")
    points = profile["points"]
    if not isinstance(points, list) or not 1 <= len(points) <= 32:
        raise ValueError("밝기 구간은 1~32개가 필요합니다.")
    previous = -1
    gaps = []
    for index, point in enumerate(points):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("구간은 [기준 lux, 밝기 %] 형식이어야 합니다.")
        lux, brightness = point
        if type(lux) not in (int, float) or not math.isfinite(lux) or not previous < lux <= 65535:
            raise ValueError("기준 조도는 중복 없이 0~65535 lux 오름차순으로 입력하세요.")
        if index == 0 and lux != 0:
            raise ValueError("첫 구간은 0 lux부터 시작해야 합니다.")
        if type(brightness) is not int or not 0 <= brightness <= 100:
            raise ValueError("구간 밝기는 0~100 정수여야 합니다.")
        if index:
            gaps.append(lux - previous)
        previous = lux
    for field, maximum in (("hysteresis_lux", 65535), ("hold_seconds", 10)):
        value = profile[field]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValueError(f"잘못된 {field}")
    if gaps and profile["hysteresis_lux"] >= min(gaps):
        raise ValueError("하강 이력은 가장 좁은 조도 구간의 폭보다 작아야 합니다.")
    return profile


def validate_profiles(profiles, selected):
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 32:
        raise ValueError("사용자 밝기 프로필은 1~32개가 필요합니다.")
    names = []
    for profile in profiles:
        validate_profile(profile)
        names.append(profile["name"])
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("밝기 프로필 이름이 중복됩니다.")
    if not isinstance(selected, str) or selected not in names:
        raise ValueError("선택한 밝기 프로필을 찾을 수 없습니다.")


class StepBrightness:
    def __init__(self, profile):
        self.profile = deepcopy(validate_profile(profile))
        self.points = self.profile["points"]
        self.thresholds = [row[0] for row in self.points]
        self.reset()

    def reset(self):
        self.index = None
        self.candidate = None
        self.candidate_since = None

    def observe(self, lux, now):
        if type(lux) not in (int, float) or not math.isfinite(lux) or lux < 0:
            raise ValueError("유효한 lux 필요")
        if self.index is None:
            self.index = bisect_right(self.thresholds, lux) - 1
        candidate = self.index
        while candidate + 1 < len(self.points) and lux >= self.thresholds[candidate + 1]:
            candidate += 1
        while candidate > 0 and lux < self.thresholds[candidate] - self.profile["hysteresis_lux"]:
            candidate -= 1
        if candidate == self.index:
            self.candidate = self.candidate_since = None
        else:
            if self.candidate != candidate:
                self.candidate, self.candidate_since = candidate, now
            if now - self.candidate_since >= self.profile["hold_seconds"]:
                self.index = candidate
                self.candidate = self.candidate_since = None
        return self.points[self.index][1]
