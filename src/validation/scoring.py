"""5개 지표 기반 최종 점수 계산기."""
from __future__ import annotations

import math

from src.data.models import HardFail, ItineraryPlan, POI, Scores
from src.validation.warning import INTENT_VECTORS

WEIGHTS = {
    "efficiency":     0.30,
    "feasibility":    0.25,
    "purpose_fit":    0.20,
    "flow":           0.15,
    "area_intensity": 0.10,
}

HARD_FAIL_SCORE_CAP: int = 59

_EARTH_R = 6371.0  # km


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _EARTH_R * math.asin(math.sqrt(a))


def _get_travel_min(matrix: dict, i: int, j: int, origin: POI, dest: POI) -> float:
    entry = (matrix.get(i) or {}).get(j)
    if entry and "travel_min" in entry:
        return float(entry["travel_min"])
    dist_km = _haversine_km(origin.lat, origin.lng, dest.lat, dest.lng)
    return dist_km / (22.0 / 60.0)


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


class ScoreCalculator:
    """5개 지표 → Final Score (0~100) 계산기. External I/O 없음."""

    def compute(
        self,
        plan: ItineraryPlan,
        pois: list[POI],
        matrix: dict,
        hard_fails: list[HardFail],
    ) -> tuple[Scores, int]:
        """5개 지표 계산 + Final Score (0~100) 반환.

        hard_fails 있으면 Final Score ≤ 59.
        반환: (Scores, final_score)
        """
        efficiency     = self._calc_efficiency(pois, matrix)
        feasibility    = self._calc_feasibility(pois, matrix, hard_fails)
        purpose_fit    = self._calc_purpose_fit(plan, pois)
        flow           = self._calc_flow(pois, matrix)
        area_intensity = self._calc_area_intensity(pois)

        scores = Scores(
            efficiency=round(efficiency, 4),
            feasibility=round(feasibility, 4),
            purpose_fit=round(purpose_fit, 4),
            flow=round(flow, 4),
            area_intensity=round(area_intensity, 4),
        )

        raw = sum(getattr(scores, k) * w for k, w in WEIGHTS.items())
        final_score = round(raw * 100)
        if hard_fails:
            final_score = min(final_score, HARD_FAIL_SCORE_CAP)

        return scores, max(0, min(100, final_score))

    def _calc_efficiency(self, pois: list[POI], matrix: dict) -> float:
        """Efficiency = nn_heuristic_km / actual_total_km, clamped to [0, 1]."""
        if len(pois) <= 1:
            return 1.0
        actual_km = sum(
            _haversine_km(pois[i].lat, pois[i].lng, pois[i + 1].lat, pois[i + 1].lng)
            for i in range(len(pois) - 1)
        )
        if actual_km == 0:
            return 1.0
        nn_km = _nn_heuristic_km(pois)
        return min(1.0, nn_km / actual_km)

    def _calc_feasibility(
        self,
        pois: list[POI],
        matrix: dict,
        hard_fails: list[HardFail],
    ) -> float:
        """Feasibility = hard×0.5 + temporal×0.3 + human×0.2."""
        hard = 0.0 if hard_fails else 1.0

        total_dwell = sum(p.duration_min for p in pois)
        total_travel_min = sum(
            _get_travel_min(matrix, i - 1, i, pois[i - 1], pois[i])
            for i in range(1, len(pois))
        )
        total_min = total_dwell + total_travel_min
        threshold = 720.0  # 12시간
        excess_ratio = max(0.0, (total_min - threshold) / threshold)
        temporal = max(0.0, 1.0 - excess_ratio)

        total_km = sum(
            _haversine_km(pois[i].lat, pois[i].lng, pois[i + 1].lat, pois[i + 1].lng)
            for i in range(len(pois) - 1)
        ) if len(pois) > 1 else 0.0
        human = 1.0 - min(1.0, total_km / 50.0)

        return hard * 0.5 + temporal * 0.3 + human * 0.2

    def _calc_purpose_fit(self, plan: ItineraryPlan, pois: list[POI]) -> float:
        """1 - cosine_distance(intent_vector, activity_vector)."""
        if not plan.travel_type:
            return 0.5
        intent = INTENT_VECTORS.get(plan.travel_type)
        if not intent:
            return 0.5
        total = len(pois)
        if total == 0:
            return 0.5
        cat_count: dict[str, float] = {}
        for poi in pois:
            cat = str(poi.category) if poi.category else "other"
            if cat not in ("12", "14", "15", "38", "39"):
                cat = "other"
            cat_count[cat] = cat_count.get(cat, 0.0) + 1.0
        activity = {k: v / total for k, v in cat_count.items()}
        return max(0.0, min(1.0, 1.0 - self._cosine_distance(intent, activity)))

    def _calc_flow(self, pois: list[POI], matrix: dict) -> float:
        """1 - (backtracking×0.5 + revisit_area×0.3 + cluster_switch×0.2)."""
        n = len(pois)
        if n <= 1:
            return 1.0

        actual_km = sum(
            _haversine_km(pois[i].lat, pois[i].lng, pois[i + 1].lat, pois[i + 1].lng)
            for i in range(n - 1)
        )
        nn_km = _nn_heuristic_km(pois)
        backtrack_ratio = (
            max(0.0, (actual_km - nn_km) / actual_km) if actual_km > 0 else 0.0
        )

        seen: dict[str, bool] = {}
        prev_cat: str | None = None
        revisit_count = 0
        for poi in pois:
            cat = poi.category or ""
            if cat and cat in seen and cat != prev_cat:
                revisit_count += 1
            seen[cat] = True
            prev_cat = cat
        revisit_ratio = revisit_count / max(1, n - 1)

        switches = sum(
            1 for i in range(1, n) if pois[i].category != pois[i - 1].category
        )
        switch_ratio = switches / max(1, n - 1)

        flow = 1.0 - (backtrack_ratio * 0.5 + revisit_ratio * 0.3 + switch_ratio * 0.2)
        return max(0.0, min(1.0, flow))

    def _calc_area_intensity(self, pois: list[POI]) -> float:
        """1 - dominant_category_ratio. 분산될수록 1에 가까움."""
        cats = [p.category for p in pois if p.category]
        if not cats:
            return 1.0
        cat_counts: dict[str, int] = {}
        for c in cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1
        dominant_ratio = max(cat_counts.values()) / len(cats)
        return 1.0 - dominant_ratio

    @staticmethod
    def _cosine_distance(v1: dict, v2: dict) -> float:
        keys = set(v1) | set(v2)
        dot = sum(v1.get(k, 0.0) * v2.get(k, 0.0) for k in keys)
        norm1 = math.sqrt(sum(x ** 2 for x in v1.values()))
        norm2 = math.sqrt(sum(x ** 2 for x in v2.values()))
        if norm1 == 0 or norm2 == 0:
            return 1.0
        return 1.0 - dot / (norm1 * norm2)
