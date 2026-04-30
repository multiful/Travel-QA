"""Neo4j 제거 타당성 분석 — 설계 의도 vs 현재 Python 로직 커버리지 비교.

Neo4j가 SUMMARY.md에서 맡기로 한 3가지 역할:
  Role-A: 비연속 구역 재진입(백트래킹) 탐지
  Role-B: 동선 역행 수치화 (지리 순서 vs 시간 순서 교차 비교)
  Role-C: 시간대별 일정 밀도(TimeSlot 과밀) 탐지

각 역할에 대해:
  - Neo4j라면 탐지했을 케이스를 시뮬레이션
  - 현재 Python 모듈(vrptw/cluster_dispersion)이 실제로 탐지하는지 검증

Usage:
    python scripts/neo4j_coverage_analysis.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

from src.data.models import VRPTWDay, VRPTWPlace, VRPTWRequest
from src.scoring.cluster_dispersion import evaluate_cluster_dispersion
from src.scoring.travel_ratio import evaluate_travel_ratio
from src.validation.vrptw_engine import HaversineMatrix, VRPTWEngine


# ── 테스트용 POI 좌표 (실제 위치 기반) ──────────────────────────────────
POI_COORDS = {
    # (lat, lng, sigungu_code, open, close)
    "강남역":        (37.4979, 127.0276, "11680", "00:00", "23:59"),
    "코엑스":        (37.5115, 127.0590, "11680", "10:00", "22:00"),
    "홍대입구역":    (37.5574, 126.9248, "11440", "00:00", "23:59"),
    "연남동":        (37.5634, 126.9259, "11440", "10:00", "22:00"),
    "명동":          (37.5636, 126.9869, "11140", "10:00", "22:00"),
    "경복궁":        (37.5796, 126.9770, "11110", "09:00", "18:00"),
    "인사동":        (37.5742, 126.9856, "11110", "10:00", "22:00"),
    "이태원":        (37.5340, 126.9947, "11590", "10:00", "23:00"),
    "남산타워":      (37.5512, 126.9882, "11140", "10:00", "23:00"),
    "잠실롯데월드":  (37.5110, 127.0980, "11710", "09:30", "21:00"),
    "송파올림픽공원":(37.5207, 127.1217, "11710", "09:00", "18:00"),
    "여의도":        (37.5219, 126.9245, "11560", "00:00", "23:59"),
}


def make_place(
    name: str,
    stay_min: int = 60,
    is_depot: bool = False,
) -> VRPTWPlace:
    lat, lng, _, open_, close = POI_COORDS[name]
    return VRPTWPlace(
        name=name, lat=lat, lng=lng,
        open=open_, close=close,
        stay_duration=stay_min,
        is_depot=is_depot,
    )


def sigungu_for(name: str) -> str:
    return POI_COORDS[name][2]


# ── Neo4j 백트래킹 탐지 시뮬레이션 ──────────────────────────────────────

def neo4j_backtrack_count(place_names: list[str]) -> int:
    """Neo4j IN_AREA 노드 로직 시뮬레이션.

    방문 순서에서 이미 방문한 Area(시군구)에 비연속으로 재진입하는 횟수를 계산.
    (강남→홍대→강남) → 1회
    """
    visited: list[str] = []
    backtrack = 0
    seen: set[str] = set()
    for name in place_names:
        area = sigungu_for(name)
        if area in seen and (not visited or visited[-1] != area):
            backtrack += 1
        seen.add(area)
        visited.append(area)
    return backtrack


def neo4j_timeslot_density(place_names: list[str], stay_min: int = 60) -> dict[str, int]:
    """Neo4j TimeSlot 노드 밀도 시뮬레이션.

    09:00 출발, 각 POI를 순서대로 방문했을 때 시간대별 점유 수 계산.
    """
    matrix = HaversineMatrix()
    places = [make_place(n, stay_min) for n in place_names]
    slots: dict[str, int] = {}
    current = 9 * 60  # 09:00 in minutes

    for i, place in enumerate(places):
        if i > 0:
            travel_s = matrix.get_travel_time(places[i - 1], place)
            current += travel_s / 60
        arrive = max(current, place.open_minutes)
        depart = arrive + stay_min
        # 1시간 단위 슬롯 점유
        h = int(arrive // 60)
        while h * 60 < depart:
            key = f"{h:02d}:00"
            slots[key] = slots.get(key, 0) + 1
            h += 1
        current = depart

    return slots


# ── 케이스별 비교 함수 ──────────────────────────────────────────────────

@dataclass
class CoverageResult:
    case: str
    neo4j_would_detect: bool
    python_detects: bool
    neo4j_detail: str
    python_detail: str

    @property
    def covered(self) -> bool:
        return self.python_detects or not self.neo4j_would_detect


def run_vrptw(days_names: list[list[str]], stay_min: int = 60) -> tuple:
    """VRPTWEngine + cluster_dispersion 실행, (vrptw_result, dispersion_report) 반환."""
    engine = VRPTWEngine(ortools_available=False)
    days = [VRPTWDay(places=[make_place(n, stay_min) for n in day]) for day in days_names]
    request = VRPTWRequest(days=days)
    vrptw = engine.validate(request)

    sigungu = [[sigungu_for(n) for n in day] for day in days_names]
    disp = evaluate_cluster_dispersion(days, sigungu)

    ratio = evaluate_travel_ratio(days)

    return vrptw, disp, ratio


def print_result(r: CoverageResult) -> None:
    icon = "✓" if r.python_detects else ("△" if not r.neo4j_would_detect else "✗")
    print(f"\n  [{icon}] {r.case}")
    print(f"      Neo4j 탐지 여부 : {'YES — ' + r.neo4j_detail if r.neo4j_would_detect else 'NO'}")
    print(f"      Python 탐지 여부: {'YES — ' + r.python_detail if r.python_detects else 'NO (미탐지)'}")


# ════════════════════════════════════════════════════════════════════════════
# Role-A: 비연속 구역 재진입(백트래킹) 탐지
# ════════════════════════════════════════════════════════════════════════════

def test_role_a() -> list[CoverageResult]:
    results = []

    # A-1: 소규모 백트래킹 (강남→홍대→강남) — 시군구 전환 2회
    names = ["강남역", "홍대입구역", "코엑스"]  # 강남구→마포구→강남구
    bt = neo4j_backtrack_count(names)
    vrptw, disp, _ = run_vrptw([names])
    sw = disp.per_day[0].sigungu_switches
    gap = vrptw.efficiency_gap

    bt_py = disp.per_day[0].area_backtrack_count
    results.append(CoverageResult(
        case="A-1: 소규모 백트래킹 (강남→홍대→강남, 시군구 전환 2회)",
        neo4j_would_detect=bt >= 1,
        neo4j_detail=f"비연속 구역 재진입 {bt}회 탐지",
        python_detects=bt_py >= 1 or sw >= 3 or (gap is not None and gap > 0.20),
        python_detail=(
            f"area_backtrack={bt_py}(M3 신규), sigungu_switches={sw}(임계 3), "
            + (f"efficiency_gap={gap:.1%}" if gap is not None else "gap=None")
        ),
    ))

    # A-2: 명확한 백트래킹 (강남→홍대→강남→이태원→강남, 전환 4회)
    names2 = ["강남역", "홍대입구역", "코엑스", "이태원", "잠실롯데월드"]
    # 강남구→마포구→강남구→용산구→송파구 (전환4회, 재진입1회)
    bt2 = neo4j_backtrack_count(names2)
    vrptw2, disp2, _ = run_vrptw([names2])
    sw2 = disp2.per_day[0].sigungu_switches
    gap2 = vrptw2.efficiency_gap
    km2 = disp2.per_day[0].max_pairwise_km
    bt2_py = disp2.per_day[0].area_backtrack_count

    results.append(CoverageResult(
        case="A-2: 명확한 백트래킹 (5-POI, 시군구 전환 4회)",
        neo4j_would_detect=bt2 >= 1,
        neo4j_detail=f"비연속 구역 재진입 {bt2}회",
        python_detects=bt2_py >= 1 or sw2 >= 3 or km2 >= 30.0,
        python_detail=(
            f"area_backtrack={bt2_py}(M3), sigungu_switches={sw2}(임계 3), "
            f"max_km={km2:.1f}, penalty={disp2.total_penalty}"
        ),
    ))

    # A-3: 백트래킹 없는 순방향 동선 (강남→송파→잠실)
    names3 = ["강남역", "이태원", "명동", "경복궁"]
    bt3 = neo4j_backtrack_count(names3)
    _, disp3, _ = run_vrptw([names3])
    sw3 = disp3.per_day[0].sigungu_switches
    bt3_py = disp3.per_day[0].area_backtrack_count

    results.append(CoverageResult(
        case="A-3: 순방향 동선 (False-positive 검사, 탐지=0이어야 정상)",
        neo4j_would_detect=bt3 >= 1,
        neo4j_detail=f"비연속 재진입 {bt3}회",
        python_detects=bt3_py >= 1,  # M3만으로 판정 — sw는 False-positive 발생 가능
        python_detail=f"area_backtrack={bt3_py}(M3, 0이면 정상), sigungu_switches={sw3}",
    ))

    return results


# ════════════════════════════════════════════════════════════════════════════
# Role-B: 동선 역행 수치화
# ════════════════════════════════════════════════════════════════════════════

def test_role_b() -> list[CoverageResult]:
    results = []

    # B-1: 심각한 동선 역행 (서울 북→남→북→남 패턴)
    # 경복궁(북)→잠실(남동)→인사동(북)→여의도(서)
    names = ["경복궁", "잠실롯데월드", "인사동", "여의도"]
    vrptw, disp, ratio = run_vrptw([names])
    km = disp.per_day[0].max_pairwise_km
    has_penalty = disp.total_penalty > 0 or ratio.total_penalty > 0

    results.append(CoverageResult(
        case="B-1: 극단적 동선 역행 (경복궁→잠실→인사동→여의도)",
        neo4j_would_detect=True,  # 지리 순서 vs 시간 순서 역전으로 탐지
        neo4j_detail="SCHEDULED_AT 시간 순서 vs IN_AREA 지리 순서 역전",
        python_detects=has_penalty or km >= 30.0,
        python_detail=(
            f"max_km={km:.1f}(임계 30), "
            f"disp_penalty={disp.total_penalty}, "
            f"ratio_penalty={ratio.total_penalty}, "
            f"deep_dive={len(vrptw.deep_dive)}건"
        ),
    ))

    # B-2: 효율적인 순환 동선 (False-positive)
    # 경복궁→인사동→명동→남산타워 (지리적으로 순방향)
    names2 = ["경복궁", "인사동", "명동", "남산타워"]
    vrptw2, disp2, ratio2 = run_vrptw([names2])
    km2 = disp2.per_day[0].max_pairwise_km

    results.append(CoverageResult(
        case="B-2: 효율적 순환 동선 (False-positive 검사)",
        neo4j_would_detect=False,
        neo4j_detail="역행 없음",
        python_detects=disp2.total_penalty > 0 or ratio2.total_penalty > 0,
        python_detail=(
            f"max_km={km2:.1f}, disp_penalty={disp2.total_penalty}, "
            f"ratio_penalty={ratio2.total_penalty}"
        ),
    ))

    return results


# ════════════════════════════════════════════════════════════════════════════
# Role-C: 시간대별 일정 밀도(TimeSlot 과밀) 탐지
# ════════════════════════════════════════════════════════════════════════════

def test_role_c() -> list[CoverageResult]:
    results = []

    # C-1: 오전 과밀 일정 (6개 POI를 오전에 몰아 넣기, stay 30분씩)
    names = ["경복궁", "인사동", "명동", "남산타워", "이태원", "홍대입구역"]
    slots = neo4j_timeslot_density(names, stay_min=30)
    peak_count = max(slots.values()) if slots else 0
    neo4j_peak_hour = [k for k, v in slots.items() if v == peak_count]

    vrptw, disp, ratio = run_vrptw([names], stay_min=30)
    fatigue_items = [d for d in vrptw.deep_dive if d.rule == "fatigue"]
    has_fatigue = len(fatigue_items) > 0

    results.append(CoverageResult(
        case="C-1: 오전 과밀 일정 (6 POI × 30분, 하루 내)",
        neo4j_would_detect=peak_count >= 3,
        neo4j_detail=f"피크 시간대 {neo4j_peak_hour} 동시 {peak_count}개 POI",
        python_detects=has_fatigue or ratio.overall_ratio >= 0.20,
        python_detail=(
            f"fatigue 탐지={has_fatigue}, "
            f"travel_ratio={ratio.overall_ratio:.1%}(임계 20%), "
            f"deep_dive={len(vrptw.deep_dive)}건"
        ),
    ))

    # C-2: 적정 일정 (4 POI × 90분, 여유 있는 하루)
    names2 = ["경복궁", "인사동", "명동", "남산타워"]
    slots2 = neo4j_timeslot_density(names2, stay_min=90)
    peak2 = max(slots2.values()) if slots2 else 0

    vrptw2, disp2, ratio2 = run_vrptw([names2], stay_min=90)
    fatigue2 = [d for d in vrptw2.deep_dive if d.rule == "fatigue"]

    results.append(CoverageResult(
        case="C-2: 적정 일정 (4 POI × 90분, False-positive 검사)",
        neo4j_would_detect=peak2 >= 3,
        neo4j_detail=f"최고 밀도 {peak2}",
        python_detects=len(fatigue2) > 0,
        python_detail=f"fatigue 탐지={len(fatigue2) > 0}, ratio={ratio2.overall_ratio:.1%}",
    ))

    return results


# ════════════════════════════════════════════════════════════════════════════
# 실행 및 요약
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 65)
    print("  Neo4j 제거 타당성 분석 — 설계 의도 vs Python 로직 커버리지")
    print("=" * 65)

    all_results: list[CoverageResult] = []

    print("\n【Role-A】비연속 구역 재진입(백트래킹) 탐지")
    for r in test_role_a():
        print_result(r)
        all_results.append(r)

    print("\n【Role-B】동선 역행 수치화")
    for r in test_role_b():
        print_result(r)
        all_results.append(r)

    print("\n【Role-C】시간대별 일정 밀도 탐지")
    for r in test_role_c():
        print_result(r)
        all_results.append(r)

    # 요약
    neo4j_detectable = [r for r in all_results if r.neo4j_would_detect]
    covered = [r for r in neo4j_detectable if r.python_detects]
    missed = [r for r in neo4j_detectable if not r.python_detects]

    print("\n" + "=" * 65)
    print("  커버리지 요약")
    print("=" * 65)
    print(f"  Neo4j가 탐지했을 케이스  : {len(neo4j_detectable)}개")
    print(f"  Python 로직이 커버하는 수: {len(covered)}개")
    print(f"  Python 로직이 미탐지한 수: {len(missed)}개")
    coverage_pct = len(covered) / len(neo4j_detectable) * 100 if neo4j_detectable else 100
    print(f"  커버리지                  : {coverage_pct:.0f}%")

    if missed:
        print("\n  ⚠ 미탐지 케이스:")
        for r in missed:
            print(f"    - {r.case}")
            print(f"      → {r.neo4j_detail}")

    print("\n  결론:")
    if coverage_pct == 100:
        print("  ✓ 현재 Python 로직이 Neo4j 설계 역할을 완전히 커버합니다.")
        print("  → Neo4j 제거 가능.")
    elif coverage_pct >= 80:
        print("  △ 대부분 커버되나 일부 케이스에서 미탐지가 있습니다.")
        print("  → 미탐지 케이스를 Python으로 보완 후 제거 권장.")
    else:
        print("  ✗ Python 로직만으로는 탐지율이 부족합니다.")
        print("  → Neo4j 유지 또는 Python으로 전면 재구현 필요.")


if __name__ == "__main__":
    main()
