"""Warning 탐지기 (동선 비효율·일정 과밀·체력 부담·목적 부적합·구역 재방문)."""
from __future__ import annotations

import math

from src.data.models import ItineraryPlan, POI, Warning
from src.data.party_config import get_party_profile

DEFAULT_START_MINUTES: int = 9 * 60  # 09:00

WARNING_TYPES = {
    "DENSE_SCHEDULE":    ("일정 과밀",     "Medium"),
    "INEFFICIENT_ROUTE": ("동선 비효율",   "Medium"),
    "PHYSICAL_STRAIN":   ("체력 부담",     "Medium"),
    "PURPOSE_MISMATCH":  ("목적 부적합",   "Medium-Low"),
    "AREA_REVISIT":      ("구역 재방문",   "Medium"),
}

INTENT_VECTORS: dict[str, dict[str, float]] = {
    "cultural":  {"14": 0.6, "12": 0.2, "15": 0.1, "other": 0.1},
    "nature":    {"12": 0.5, "15": 0.3, "14": 0.1, "other": 0.1},
    "shopping":  {"38": 0.5, "12": 0.3, "14": 0.1, "other": 0.1},
    "food":      {"39": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
    "adventure": {"15": 0.6, "12": 0.2, "14": 0.1, "other": 0.1},
}

_EARTH_R = 6371.0  # km


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def _cosine_distance(v1: dict[str, float], v2: dict[str, float]) -> float:
    keys = set(v1) | set(v2)
    dot = sum(v1.get(k, 0.0) * v2.get(k, 0.0) for k in keys)
    norm1 = math.sqrt(sum(x ** 2 for x in v1.values()))
    norm2 = math.sqrt(sum(x ** 2 for x in v2.values()))
    if norm1 == 0 or norm2 == 0:
        return 1.0
    return 1.0 - dot / (norm1 * norm2)


def _get_travel_min(matrix: dict, i: int, j: int, origin: POI, dest: POI) -> float:
    entry = (matrix.get(i) or {}).get(j)
    if entry and "travel_min" in entry:
        return float(entry["travel_min"])
    dist_km = _haversine_km(origin.lat, origin.lng, dest.lat, dest.lng)
    return dist_km / (22.0 / 60.0)  # 22 km/h 유효 속도


def _total_time_min(pois: list[POI], matrix: dict) -> float:
    dwell = sum(p.duration_min for p in pois)
    travel = sum(
        _get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i])
        for i in range(1, len(pois))
    )
    return dwell + travel


def _total_km(pois: list[POI]) -> float:
    return sum(
        _haversine_km(pois[i].lat, pois[i].lng, pois[i + 1].lat, pois[i + 1].lng)
        for i in range(len(pois) - 1)
    )


def _nn_heuristic_km(pois: list[POI]) -> float:
    if len(pois) <= 1:
        return 0.0
    visited = {0}
    current = 0
    total = 0.0
    while len(visited) < len(pois):
        best_d = float("inf")
        best_j = -1
        for j in range(len(pois)):
            if j not in visited:
                d = _haversine_km(
                    pois[current].lat, pois[current].lng,
                    pois[j].lat, pois[j].lng,
                )
                if d < best_d:
                    best_d, best_j = d, j
        if best_j == -1:
            break
        total += best_d
        visited.add(best_j)
        current = best_j
    return total


class WarningDetector:
    """여행 일정의 Soft Warning 조건을 탐지한다.

    External I/O 없음. matrix: dict[int, dict[int, dict]] 인덱스 기반.
    피로도 임계·체력 부담 기준은 party_type별 PartyProfile에서 동적으로 결정된다.
    """

    STRAIN_THRESHOLD_KM: float = 30.0  # 기준 그룹(혼자/친구) 체력 부담 임계
    BACKTRACK_THRESHOLD: float = 0.3   # 30% 초과 이동거리 비효율
    PURPOSE_FIT_THRESHOLD: float = 0.5
    CONSECUTIVE_REVISIT: int = 2       # 같은 카테고리 연속 ≥ 2회

    def detect(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
    ) -> list[Warning]:
        """Warning 목록 반환. 없으면 빈 리스트."""
        warns: list[Warning] = []
        warns.extend(self._check_dense_schedule(plan, pois, matrix))
        warns.extend(self._check_inefficient_route(pois))
        warns.extend(self._check_physical_strain(plan, pois))
        warns.extend(self._check_purpose_mismatch(plan, pois))
        warns.extend(self._check_area_revisit(pois))
        return warns

    def _check_dense_schedule(
        self, plan: ItineraryPlan, pois: list[POI], matrix: dict
    ) -> list[Warning]:
        profile = get_party_profile(plan.party_type)
        threshold_min = profile.fatigue_hours * 60
        total_min = _total_time_min(pois, matrix)
        if total_min <= threshold_min:
            return []
        _, confidence = WARNING_TYPES["DENSE_SCHEDULE"]
        return [Warning(
            warning_type="DENSE_SCHEDULE",
            message=(
                f"총 일정 소요 시간 {total_min:.0f}분 ({total_min / 60:.1f}시간)이 "
                f"'{plan.party_type}' 그룹 피로도 한계 {profile.fatigue_hours}시간을 초과합니다."
            ),
            confidence=confidence,
        )]

    def _check_inefficient_route(self, pois: list[POI]) -> list[Warning]:
        if len(pois) <= 2:
            return []
        actual_km = _total_km(pois)
        if actual_km == 0:
            return []
        nn_km = _nn_heuristic_km(pois)
        ratio = (actual_km - nn_km) / actual_km
        if ratio <= self.BACKTRACK_THRESHOLD:
            return []
        _, confidence = WARNING_TYPES["INEFFICIENT_ROUTE"]
        return [Warning(
            warning_type="INEFFICIENT_ROUTE",
            message=(
                f"현재 방문 순서의 이동 거리({actual_km:.1f}km)가 최적 경로 대비 "
                f"{ratio:.1%} 더 깁니다. 방문 순서를 재배치해 보세요."
            ),
            confidence=confidence,
        )]

    def _check_physical_strain(self, plan: ItineraryPlan, pois: list[POI]) -> list[Warning]:
        profile = get_party_profile(plan.party_type)
        # speed_factor < 1.0 → 취약 그룹일수록 더 낮은 거리에서 경고
        threshold_km = self.STRAIN_THRESHOLD_KM * profile.speed_factor
        total_km = _total_km(pois)
        if total_km <= threshold_km:
            return []
        _, confidence = WARNING_TYPES["PHYSICAL_STRAIN"]
        return [Warning(
            warning_type="PHYSICAL_STRAIN",
            message=(
                f"총 이동 거리 {total_km:.1f}km가 "
                f"'{plan.party_type}' 그룹 체력 한계 {threshold_km:.0f}km를 초과합니다."
            ),
            confidence=confidence,
        )]

    def _check_purpose_mismatch(self, plan: ItineraryPlan, pois: list[POI]) -> list[Warning]:
        if not plan.travel_type:
            return []
        intent = INTENT_VECTORS.get(plan.travel_type)
        if not intent:
            return []

        total = len(pois)
        if total == 0:
            return []

        cat_count: dict[str, float] = {}
        for poi in pois:
            cat = str(poi.category) if poi.category else "other"
            if cat not in ("12", "14", "15", "38", "39"):
                cat = "other"
            cat_count[cat] = cat_count.get(cat, 0.0) + 1.0
        activity = {k: v / total for k, v in cat_count.items()}

        purpose_fit = 1.0 - _cosine_distance(intent, activity)
        if purpose_fit >= self.PURPOSE_FIT_THRESHOLD:
            return []

        _, confidence = WARNING_TYPES["PURPOSE_MISMATCH"]
        return [Warning(
            warning_type="PURPOSE_MISMATCH",
            message=(
                f"여행 테마 '{plan.travel_type}'과 실제 장소 구성의 일치도가 "
                f"{purpose_fit:.2f}로 낮습니다. 테마에 맞는 장소 선택을 권장합니다."
            ),
            confidence=confidence,
        )]

    def _check_area_revisit(self, pois: list[POI]) -> list[Warning]:
        if len(pois) < self.CONSECUTIVE_REVISIT:
            return []
        max_run = 1
        cur_run = 1
        for i in range(1, len(pois)):
            if pois[i].category and pois[i].category == pois[i - 1].category:
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 1
        if max_run < self.CONSECUTIVE_REVISIT:
            return []
        _, confidence = WARNING_TYPES["AREA_REVISIT"]
        return [Warning(
            warning_type="AREA_REVISIT",
            message=(
                f"동일 카테고리 장소가 {max_run}회 연속 배치되어 있습니다. "
                "다양한 유형의 장소를 번갈아 방문하면 여행이 더 풍성해집니다."
            ),
            confidence=confidence,
        )]
