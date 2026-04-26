"""경로 밀집도 / 번개패턴 탐지 (모듈 ⑥) — Per-day 검증.

사용자 의도 (Q3):
  "1일차에는 목적지 근처로, 2일차에는 또 다른 목적지" — 하루 안에서 너무
  멀리 떨어진 장소 배치 시 패널티. 다일 간 거리(Day1↔Day2)는 패널티 없음.

두 메트릭 (둘 다 위반 시 합산 캡 -20 적용 — 이중 패널티 방지):
  M1. sigungu_switches (per-day) — 같은 day 안에서 lDongSignguCd 변경 횟수
  M2. max_pairwise_distance_km (per-day) — 같은 day 안 좌표쌍 최대 직선거리
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from src.data.models import DeepDiveItem, VRPTWDay, VRPTWPlace


# ── M1: 시군구 전환 임계값 ────────────────────────────────────────────
SWITCH_WARN: int = 3       # 3회 → -5
SWITCH_CRIT: int = 4       # 4회 이상 → -10
PENALTY_SWITCH_WARN: int = 5
PENALTY_SWITCH_CRIT: int = 10

# ── M2: 최대 직선거리 임계값 (km) ─────────────────────────────────────
DIST_WARN_KM: float = 30.0
DIST_RISK_KM: float = 50.0
DIST_CRIT_KM: float = 100.0
PENALTY_DIST_WARN: int = 5
PENALTY_DIST_RISK: int = 10
PENALTY_DIST_CRIT: int = 20

# ── 합산 캡 ──────────────────────────────────────────────────────────
COMBINED_PENALTY_CAP: int = 20


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 점 직선거리 (km)."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class DayDispersionMetric:
    """일자별 밀집도 측정."""
    day_index: int
    sigungu_switches: int
    max_pairwise_km: float
    sigungu_codes_visited: list[str]


@dataclass(frozen=True)
class ClusterDispersionReport:
    per_day: list[DayDispersionMetric]
    total_penalty: int
    deep_dive: list[DeepDiveItem]


def _compute_day_dispersion(
    day_idx: int,
    places: list[VRPTWPlace],
    sigungu_codes: list[str | None] | None = None,
) -> DayDispersionMetric:
    """하루 일정의 두 메트릭 계산."""
    # ── M1: 시군구 전환 횟수 ──
    sigungus: list[str] = []
    if sigungu_codes:
        for code in sigungu_codes:
            if code:
                sigungus.append(code)
    switches = sum(1 for a, b in zip(sigungus, sigungus[1:]) if a != b)

    # ── M2: 최대 직선거리 (좌표쌍 O(n²), 장소 4~8개라 무시할 수준) ──
    max_dist = 0.0
    n = len(places)
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine_km(
                places[i].lat, places[i].lng,
                places[j].lat, places[j].lng,
            )
            if d > max_dist:
                max_dist = d

    return DayDispersionMetric(
        day_index=day_idx,
        sigungu_switches=switches,
        max_pairwise_km=round(max_dist, 2),
        sigungu_codes_visited=list(set(sigungus)),
    )


def _switch_penalty(switches: int) -> int:
    if switches >= SWITCH_CRIT:
        return PENALTY_SWITCH_CRIT
    if switches >= SWITCH_WARN:
        return PENALTY_SWITCH_WARN
    return 0


def _distance_penalty(dist_km: float) -> int:
    if dist_km >= DIST_CRIT_KM:
        return PENALTY_DIST_CRIT
    if dist_km >= DIST_RISK_KM:
        return PENALTY_DIST_RISK
    if dist_km >= DIST_WARN_KM:
        return PENALTY_DIST_WARN
    return 0


def evaluate_cluster_dispersion(
    days: list[VRPTWDay],
    sigungu_codes_per_day: list[list[str | None]] | None = None,
) -> ClusterDispersionReport:
    """전체 일정의 per-day 밀집도 + 패널티 산출.

    sigungu_codes_per_day: VRPTWPlace 모델에 sigungu가 없어 별도로 받음.
                           [day_idx][place_idx] 구조. None이면 시군구 검증 스킵.
    """
    per_day: list[DayDispersionMetric] = []
    deep_dive: list[DeepDiveItem] = []
    total_penalty = 0

    for idx, day in enumerate(days):
        sg = sigungu_codes_per_day[idx] if sigungu_codes_per_day and idx < len(sigungu_codes_per_day) else None
        metric = _compute_day_dispersion(idx, day.places, sg)
        per_day.append(metric)

        # 두 메트릭 패널티 계산 + 합산 캡 적용
        sw_pen = _switch_penalty(metric.sigungu_switches)
        ds_pen = _distance_penalty(metric.max_pairwise_km)
        day_penalty = min(sw_pen + ds_pen, COMBINED_PENALTY_CAP)
        total_penalty += day_penalty

        # DeepDive 생성 — 위반된 메트릭만
        if sw_pen > 0:
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 시군구 전환 {metric.sigungu_switches}회 "
                    f"(방문: {', '.join(metric.sigungu_codes_visited)})"
                ),
                rule="cluster_dispersion_switches",
                risk="WARNING" if sw_pen == PENALTY_SWITCH_WARN else "CRITICAL",
                suggestion=(
                    "하루 안에 너무 많은 시군구를 이동합니다. "
                    "같은 지역 내 장소로 묶어주세요."
                ),
            ))
        if ds_pen > 0:
            risk = "CRITICAL" if ds_pen == PENALTY_DIST_CRIT else "WARNING"
            deep_dive.append(DeepDiveItem(
                fact=(
                    f"{idx + 1}일차 최대 직선거리 {metric.max_pairwise_km}km "
                    f"({len(day.places)}개 장소)"
                ),
                rule="cluster_dispersion_distance",
                risk=risk,  # type: ignore[arg-type]
                suggestion=(
                    "하루 안에 멀리 떨어진 장소들이 섞여 있습니다. "
                    "1일차는 목적지 근처에 집중하고, 다른 지역은 다른 날로 분리하세요."
                ),
            ))

    return ClusterDispersionReport(
        per_day=per_day,
        total_penalty=total_penalty,
        deep_dive=deep_dive,
    )
