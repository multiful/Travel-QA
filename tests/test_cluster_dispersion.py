"""Tests for src/scoring/cluster_dispersion.py — per-day 검증."""
from __future__ import annotations

import pytest

from src.data.models import VRPTWDay, VRPTWPlace
from src.scoring.cluster_dispersion import (
    COMBINED_PENALTY_CAP,
    PENALTY_DIST_CRIT,
    PENALTY_SWITCH_WARN,
    evaluate_cluster_dispersion,
)


def _make_place(name: str, lng: float, lat: float):
    return VRPTWPlace(
        name=name, lng=lng, lat=lat,
        open="09:00", close="22:00", stay_duration=60, is_depot=False,
    )


def test_compact_day_no_penalty():
    """같은 시군구 + 거리 < 30km → 패널티 0."""
    day = VRPTWDay(places=[
        _make_place("강남A", 127.027, 37.498),
        _make_place("강남B", 127.030, 37.500),
        _make_place("강남C", 127.025, 37.495),
    ])
    sg = [["680", "680", "680"]]   # 모두 강남구
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    assert report.total_penalty == 0
    assert report.per_day[0].sigungu_switches == 0
    assert report.per_day[0].max_pairwise_km < 30


def test_lightning_pattern_high_penalty():
    """1일차에 서울↔부산 섞기 → 거리 메트릭 CRITICAL + 캡 적용."""
    day = VRPTWDay(places=[
        _make_place("서울 강남", 127.027, 37.498),
        _make_place("부산 해운대", 129.157, 35.158),
        _make_place("서울 종로", 126.984, 37.572),
    ])
    sg = [["680", "260", "110"]]   # 강남구 → 해운대구 → 종로구
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    # 서울↔부산 직선거리 ~325km → CRITICAL
    assert report.per_day[0].max_pairwise_km > 100
    # 시군구 3회 전환 + 거리 CRITICAL → 합산 캡 적용
    assert report.total_penalty == COMBINED_PENALTY_CAP


def test_per_day_independence():
    """Day1=서울 / Day2=부산 (각 day 안에서는 응집) → 패널티 없음."""
    day1 = VRPTWDay(places=[
        _make_place("서울A", 127.027, 37.498),
        _make_place("서울B", 127.030, 37.500),
    ])
    day2 = VRPTWDay(places=[
        _make_place("부산A", 129.157, 35.158),
        _make_place("부산B", 129.160, 35.160),
    ])
    sg = [["680", "680"], ["260", "260"]]
    report = evaluate_cluster_dispersion([day1, day2], sigungu_codes_per_day=sg)
    assert report.total_penalty == 0


def test_sigungu_switches_only():
    """거리는 안 멀지만 시군구 전환 4회+ → 시군구 패널티만 발생."""
    day = VRPTWDay(places=[
        _make_place("A", 127.00, 37.55),   # 강남
        _make_place("B", 127.01, 37.56),   # 송파 (10km 미만)
        _make_place("C", 127.02, 37.57),   # 광진 (10km 미만)
        _make_place("D", 127.03, 37.58),   # 성동 (10km 미만)
        _make_place("E", 127.04, 37.59),   # 중구 (10km 미만)
    ])
    sg = [["680", "710", "215", "200", "140"]]   # 5개 다른 시군구 → 4회 전환
    report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=sg)
    assert report.per_day[0].sigungu_switches == 4
    assert report.total_penalty >= PENALTY_SWITCH_WARN
