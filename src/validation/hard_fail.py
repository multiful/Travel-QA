"""Hard Fail 탐지기 (운영시간 충돌·이동 불가·일정 시간 초과)."""
from __future__ import annotations

import math

from src.data.models import HardFail, ItineraryPlan, POI

DEFAULT_START_MINUTES: int = 9 * 60  # 09:00

HARD_FAIL_TYPES = {
    "OPERATING_HOURS_CONFLICT": "도착 예상 시간이 POI 운영시간 외",
    "TRAVEL_TIME_IMPOSSIBLE":   "이동시간이 이용 가능한 시간 창을 초과",
    "SCHEDULE_INFEASIBLE":      "전체 일정이 시간 내 수행 불가능",
}

_EARTH_R = 6_371_000.0  # meters


def _haversine_sec(
    lat1: float, lng1: float, lat2: float, lng2: float,
    speed_mps: float = 22_000 / 3600,
) -> float:
    """Haversine 직선거리 기반 이동 시간(초) — 중거리 기본 속도."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    dist_m = 2 * _EARTH_R * math.asin(math.sqrt(a))
    return dist_m / speed_mps


def _get_travel_min(
    matrix: dict, i: int, j: int,
    origin: POI, destination: POI,
) -> float:
    """matrix[i][j]["travel_min"] 조회, 없으면 Haversine 폴백 (분)."""
    entry = (matrix.get(i) or {}).get(j)
    if entry and "travel_min" in entry:
        return float(entry["travel_min"])
    return _haversine_sec(origin.lat, origin.lng, destination.lat, destination.lng) / 60.0


class HardFailDetector:
    """여행 일정의 Hard Fail 조건을 탐지한다.

    External I/O 없음. matrix: dict[int, dict[int, dict]] 인덱스 기반.
    matrix[i][j] = {"travel_min": float, "distance_km": float, ...}
    """

    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        start_minutes: int = DEFAULT_START_MINUTES,
    ) -> list[HardFail]:
        """Hard Fail 목록 반환. 없으면 빈 리스트."""
        fails: list[HardFail] = []
        fails.extend(self._check_operating_hours(pois, matrix, start_minutes))
        fails.extend(self._check_travel_impossible(pois, matrix, start_minutes))
        fails.extend(self._check_schedule_infeasible(pois, matrix))
        return fails

    def _check_operating_hours(
        self,
        pois: list[POI],
        matrix: dict,
        start_minutes: int,
    ) -> list[HardFail]:
        """각 POI 도착 예상 시간이 운영시간 밖이면 Hard Fail."""
        fails: list[HardFail] = []
        current_time = float(start_minutes)

        for i, poi in enumerate(pois):
            open_min = self._time_to_min(poi.open_start)
            close_min = self._time_to_min(poi.open_end)
            is_fallback = poi.open_start == "00:00" and poi.open_end == "23:59"

            arrive = (
                current_time
                if i == 0
                else current_time + _get_travel_min(matrix, i - 1, i, pois[i - 1], poi)
            )

            if not is_fallback:
                if arrive < open_min:
                    fails.append(HardFail(
                        fail_type="OPERATING_HOURS_CONFLICT",
                        message=(
                            f"'{poi.name}' 도착 예정 {self._min_to_time(arrive)}, "
                            f"운영 시작 {poi.open_start} — 아직 문을 열지 않았습니다."
                        ),
                        evidence=(
                            f"도착 {self._min_to_time(arrive)} < 운영시작 {poi.open_start}"
                        ),
                        confidence="Medium",
                        poi_name=poi.name,
                    ))
                elif arrive > close_min:
                    fails.append(HardFail(
                        fail_type="OPERATING_HOURS_CONFLICT",
                        message=(
                            f"'{poi.name}' 도착 예정 {self._min_to_time(arrive)}, "
                            f"운영 종료 {poi.open_end} — 이미 문을 닫았습니다."
                        ),
                        evidence=(
                            f"도착 {self._min_to_time(arrive)} > 운영종료 {poi.open_end}"
                        ),
                        confidence="Medium",
                        poi_name=poi.name,
                    ))

            effective_arrive = max(arrive, open_min)
            current_time = effective_arrive + poi.duration_min

        return fails

    def _check_travel_impossible(
        self,
        pois: list[POI],
        matrix: dict,
        start_minutes: int,
    ) -> list[HardFail]:
        """이동시간이 이용 가능한 시간 창을 초과하면 Hard Fail."""
        fails: list[HardFail] = []
        current_time = float(start_minutes)

        for i, poi in enumerate(pois):
            open_min = self._time_to_min(poi.open_start)

            if i == 0:
                effective_arrive = max(current_time, open_min)
                current_time = effective_arrive + poi.duration_min
                continue

            prev = pois[i - 1]
            travel_min = _get_travel_min(matrix, i - 1, i, prev, poi)
            close_min = self._time_to_min(poi.open_end)
            is_fallback = poi.open_start == "00:00" and poi.open_end == "23:59"
            available_window = close_min - current_time

            if not is_fallback and travel_min > available_window:
                fails.append(HardFail(
                    fail_type="TRAVEL_TIME_IMPOSSIBLE",
                    message=(
                        f"'{prev.name}'→'{poi.name}' 이동 시간 {travel_min:.0f}분이 "
                        f"가용 시간 창 {available_window:.0f}분을 초과합니다."
                    ),
                    evidence=(
                        f"이동 {travel_min:.0f}분 > 가용 창 {available_window:.0f}분 "
                        f"(출발 {self._min_to_time(current_time)}, "
                        f"'{poi.name}' 종료 {poi.open_end})"
                    ),
                    confidence="High",
                    poi_name=poi.name,
                ))

            arrive = current_time + travel_min
            effective_arrive = max(arrive, open_min)
            current_time = effective_arrive + poi.duration_min

        return fails

    def _check_schedule_infeasible(
        self,
        pois: list[POI],
        matrix: dict,
    ) -> list[HardFail]:
        """총 체류+이동 시간이 24시간 초과 시 Hard Fail."""
        total_dwell = sum(p.duration_min for p in pois)
        total_travel_min = 0.0
        for i in range(1, len(pois)):
            total_travel_min += _get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i])

        total_min = total_dwell + total_travel_min
        if total_min > 24 * 60:
            return [HardFail(
                fail_type="SCHEDULE_INFEASIBLE",
                message=(
                    f"총 일정 소요 시간 {total_min:.0f}분 ({total_min / 60:.1f}시간)이 "
                    f"24시간을 초과합니다."
                ),
                evidence=(
                    f"체류 {total_dwell}분 + 이동 {total_travel_min:.0f}분 "
                    f"= {total_min:.0f}분 > 1440분"
                ),
                confidence="High",
            )]
        return []

    @staticmethod
    def _time_to_min(hhmm: str) -> int:
        h, m = map(int, hhmm.split(":"))
        return h * 60 + m

    @staticmethod
    def _min_to_time(minutes: float) -> str:
        m = int(minutes)
        return f"{m // 60:02d}:{m % 60:02d}"
