"""Hard Fail 발생 장소에 대한 대안 POI 추천 엔진 (Plan B).

Hard Fail이 발생한 장소를 근처의 유사 카테고리 POI로 교체하는 대안을 제시.
외부 I/O 없음 — 입력으로 전달된 poi_pool에서만 탐색.

사용 예:
    finder = AlternativesFinder(poi_pool=nearby_pois, max_alternatives=3)
    alternatives_map = finder.build_alternatives_map(hard_fails, plan_pois)
    # → {"경복궁": [AlternativePOI(name="창덕궁", ...), ...]}
"""
from __future__ import annotations

import math
from typing import Sequence

from src.data.models import AlternativePOI, HardFail, POI

_EARTH_R = 6371.0
_MAX_SEARCH_KM = 10.0   # 기본 탐색 반경


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


class AlternativesFinder:
    """Hard Fail POI를 대체할 후보 추천기.

    Args:
        poi_pool: 탐색 대상 전체 POI 풀 (TourAPI 등 외부에서 주입).
        max_alternatives: POI 하나당 최대 추천 수.
        max_search_km: 탐색 반경(km). 이 반경 내 POI만 후보로 삼음.
    """

    def __init__(
        self,
        poi_pool: Sequence[POI],
        max_alternatives: int = 3,
        max_search_km: float = _MAX_SEARCH_KM,
    ) -> None:
        self._pool = list(poi_pool)
        self._max = max_alternatives
        self._radius = max_search_km

    def find_alternatives(
        self,
        failed_poi: POI,
        exclude_names: set[str] | None = None,
    ) -> list[AlternativePOI]:
        """failed_poi와 같은 카테고리 중 가장 가까운 POI를 반환.

        같은 카테고리가 없으면 반경 내 모든 POI를 거리 순으로 반환.
        """
        exclude = exclude_names or set()
        candidates: list[tuple[float, POI]] = []

        for poi in self._pool:
            if poi.name == failed_poi.name or poi.name in exclude:
                continue
            dist = _haversine_km(failed_poi.lat, failed_poi.lng, poi.lat, poi.lng)
            if dist <= self._radius:
                candidates.append((dist, poi))

        # 같은 카테고리 우선 정렬 → 거리 순
        candidates.sort(key=lambda x: (x[1].category != failed_poi.category, x[0]))

        return [
            AlternativePOI(
                name=poi.name,
                distance_km=round(dist, 2),
                category=poi.category,
                lat=poi.lat,
                lng=poi.lng,
            )
            for dist, poi in candidates[: self._max]
        ]

    def build_alternatives_map(
        self,
        hard_fails: Sequence[HardFail],
        plan_pois: Sequence[POI],
    ) -> dict[str, list[AlternativePOI]]:
        """Hard Fail 목록 기반으로 POI 이름 → 대안 리스트 딕셔너리 반환.

        poi_name이 None인 Hard Fail(SCHEDULE_INFEASIBLE 등)은 건너뜀.
        plan_pois의 이름들을 exclude 목록으로 넘겨 현재 일정 중복 방지.
        """
        plan_names = {p.name for p in plan_pois}
        poi_by_name: dict[str, POI] = {p.name: p for p in plan_pois}
        result: dict[str, list[AlternativePOI]] = {}

        for fail in hard_fails:
            if fail.poi_name is None or fail.poi_name in result:
                continue
            failed_poi = poi_by_name.get(fail.poi_name)
            if failed_poi is None:
                continue
            alts = self.find_alternatives(failed_poi, exclude_names=plan_names)
            result[fail.poi_name] = alts

        return result
