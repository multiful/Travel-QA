"""카카오 모빌리티 길찾기 API → TimeMatrix 어댑터.

VRPTW 엔진의 TimeMatrix 인터페이스를 구현해 즉시 swap-in 가능:

    from src.validation.kakao_matrix import KakaoMobilityMatrix
    from src.validation.vrptw_engine import VRPTWEngine

    matrix = KakaoMobilityMatrix.from_env(cache_path="data/route_cache.json")
    engine = VRPTWEngine(matrix=matrix)
    result = engine.validate(plan)

기능
----
1. 좌표쌍 캐시 (JSON 파일) — 동일 origin/destination 재호출 방지
2. 양방향 캐시 매칭 — A→B와 B→A 동일 거리로 처리
3. 일일 한도(429/quota) 자동 감지 → Haversine 폴백
4. 호출 통계 (hit/miss/api_call/fallback) 추적
5. 환경변수 KAKAO_MOBILITY_KEY (없으면 KAKAO_REST_API_KEY 폴백)

Kakao Mobility 일일 무료 한도 (참고)
- 길찾기 (자동차): 보통 1만~10만회/일 (계약에 따라)
- 한도 초과 시 429 또는 비즈 결제 필요
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from src.data.models import VRPTWPlace
from src.validation.vrptw_engine import HaversineMatrix, TimeMatrix


KAKAO_DIRECTIONS_URL = "https://apis-navi.kakaomobility.com/v1/directions"

DEFAULT_TIMEOUT_SEC: float = 5.0
DEFAULT_SLEEP_BETWEEN: float = 0.05   # 초당 ~20회 — Kakao QPS 여유
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF: float = 2.0


class KakaoMobilityMatrix(TimeMatrix):
    """카카오 모빌리티 길찾기 API 기반 TimeMatrix.

    캐시 키 형식: 'lng1,lat1|lng2,lat2' (소수점 4자리 반올림 = 약 11m 정밀도).
    is_quota_exhausted=True 가 되면 이후 호출은 모두 Haversine 폴백.

    캐시 파일은 None일 시 메모리만 사용 (일회성 검증용).
    """

    def __init__(
        self,
        api_key: str,
        cache_path: str | Path | None = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        sleep_between: float = DEFAULT_SLEEP_BETWEEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        save_every: int = 50,            # N개 호출마다 캐시 저장
    ) -> None:
        if not api_key:
            raise ValueError(
                "Kakao API key 누락. .env에 KAKAO_MOBILITY_KEY 또는 "
                "KAKAO_REST_API_KEY를 설정하세요."
            )
        self._api_key = api_key
        self._cache_path = Path(cache_path) if cache_path else None
        self._timeout = timeout_sec
        self._sleep = sleep_between
        self._max_retries = max_retries
        self._save_every = save_every

        self._cache: dict[str, int] = self._load_cache()
        self._fallback = HaversineMatrix()
        self._quota_exhausted = False
        self._stats: dict[str, int] = {
            "cache_hit": 0, "api_success": 0, "api_fail": 0, "fallback": 0,
        }
        self._dirty_count = 0    # 마지막 저장 이후 새로 추가된 캐시 항목 수

    # ── 팩토리: 환경변수에서 키 자동 로드 ────────────────────────────
    @classmethod
    def from_env(
        cls,
        cache_path: str | Path | None = None,
        env_path: str | Path | None = None,
        **kwargs: Any,
    ) -> "KakaoMobilityMatrix":
        """`.env`에서 KAKAO_MOBILITY_KEY (없으면 KAKAO_REST_API_KEY) 로드."""
        if env_path:
            cls._load_dotenv(Path(env_path))
        else:
            # 기본: 프로젝트 루트의 .env
            project_root = Path(__file__).resolve().parents[2]
            env_default = project_root / ".env"
            if env_default.exists():
                cls._load_dotenv(env_default)

        key = (
            os.environ.get("KAKAO_MOBILITY_KEY", "")
            or os.environ.get("KAKAO_REST_API_KEY", "")
        )
        return cls(api_key=key, cache_path=cache_path, **kwargs)

    @staticmethod
    def _load_dotenv(env_path: Path) -> None:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    # ── TimeMatrix 인터페이스 구현 ────────────────────────────────────
    def get_travel_time(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int:
        """origin → destination 이동시간(초). 실패 시 Haversine 폴백."""
        # 같은 지점이면 0
        if origin.lat == destination.lat and origin.lng == destination.lng:
            return 0

        # 1. 캐시 조회 (양방향)
        key_fwd = self._make_key(origin, destination)
        key_rev = self._make_key(destination, origin)
        if key_fwd in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_fwd]
        if key_rev in self._cache:
            self._stats["cache_hit"] += 1
            return self._cache[key_rev]

        # 2. API 호출 (한도 미소진 시)
        if not self._quota_exhausted:
            duration = self._call_kakao(origin, destination)
            if duration is not None:
                self._cache[key_fwd] = duration
                self._stats["api_success"] += 1
                self._maybe_save_cache()
                return duration

        # 3. Haversine 폴백
        self._stats["fallback"] += 1
        return self._fallback.get_travel_time(origin, destination)

    # ── 내부: API 호출 (재시도 포함) ─────────────────────────────────
    def _call_kakao(self, origin: VRPTWPlace, destination: VRPTWPlace) -> int | None:
        """카카오 모빌리티 호출. 성공 시 duration(초). 실패 시 None."""
        headers = {"Authorization": f"KakaoAK {self._api_key}"}
        params = {
            "origin":      f"{origin.lng},{origin.lat}",
            "destination": f"{destination.lng},{destination.lat}",
        }

        for attempt in range(1, self._max_retries + 1):
            try:
                r = requests.get(
                    KAKAO_DIRECTIONS_URL,
                    headers=headers, params=params,
                    timeout=self._timeout,
                )
                if r.status_code == 200:
                    data = r.json()
                    routes = data.get("routes", [])
                    if not routes:
                        return None
                    sections = routes[0].get("sections", [])
                    if not sections:
                        # routes[0]에 result_code 가 들어있을 수 있음
                        result_msg = routes[0].get("result_msg", "no sections")
                        # 출발/도착이 같거나 도달 불가 등
                        if "DIFFERENT" in result_msg.upper() or "NOT" in result_msg.upper():
                            return None
                        return None
                    # 카카오는 routes[0].summary.duration 또는 sections[0].duration 둘 다 제공
                    summary = routes[0].get("summary", {})
                    if "duration" in summary:
                        return int(summary["duration"])
                    return int(sections[0].get("duration", 0))

                if r.status_code == 429:
                    print("  [kakao-mobility] 429 Too Many Requests — quota exhausted")
                    self._quota_exhausted = True
                    return None

                if r.status_code in (401, 403):
                    raise RuntimeError(
                        f"인증 오류 {r.status_code} — KAKAO_MOBILITY_KEY 확인 필요"
                    )

                # 5xx 등 일시 오류 → 재시도
                wait = DEFAULT_RETRY_BACKOFF ** attempt
                time.sleep(wait)

            except requests.RequestException as e:
                wait = DEFAULT_RETRY_BACKOFF ** attempt
                if attempt < self._max_retries:
                    time.sleep(wait)
                else:
                    print(f"  [kakao-mobility] 실패: {e}")

        self._stats["api_fail"] += 1
        return None

    # ── 캐시 입출력 ──────────────────────────────────────────────────
    def _make_key(self, origin: VRPTWPlace, destination: VRPTWPlace) -> str:
        return (
            f"{origin.lng:.4f},{origin.lat:.4f}"
            f"|{destination.lng:.4f},{destination.lat:.4f}"
        )

    def _load_cache(self) -> dict[str, int]:
        if not self._cache_path or not self._cache_path.exists():
            return {}
        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            # 정수형 보장
            return {k: int(v) for k, v in data.items() if v is not None}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  [warn] 캐시 로드 실패 ({self._cache_path}): {e} — 빈 캐시로 시작")
            return {}

    def _maybe_save_cache(self) -> None:
        self._dirty_count += 1
        if self._cache_path and self._dirty_count >= self._save_every:
            self.save_cache()

    def save_cache(self) -> None:
        """현재 캐시를 디스크에 저장."""
        if not self._cache_path:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False),
            encoding="utf-8",
        )
        self._dirty_count = 0

    # ── 진단·상태 조회 ───────────────────────────────────────────────
    @property
    def stats(self) -> dict[str, int]:
        """호출 통계: cache_hit / api_success / api_fail / fallback."""
        return dict(self._stats)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def is_quota_exhausted(self) -> bool:
        return self._quota_exhausted
