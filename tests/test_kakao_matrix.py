"""KakaoMobilityMatrix 테스트 (실제 API 호출 X — 모두 mock)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import VRPTWPlace
from src.validation.kakao_matrix import KakaoMobilityMatrix


def _place(name: str, lng: float, lat: float) -> VRPTWPlace:
    return VRPTWPlace(
        name=name, lng=lng, lat=lat,
        open="09:00", close="22:00", stay_duration=60, is_depot=False,
    )


@pytest.fixture
def mock_response_ok():
    """카카오 정상 응답 — duration 600초."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = {
        "routes": [{
            "summary": {"duration": 600, "distance": 5000},
            "sections": [{"duration": 600}],
        }],
    }
    return m


@pytest.fixture
def mock_response_429():
    m = MagicMock()
    m.status_code = 429
    return m


class TestSamePoint:
    def test_same_coords_returns_zero(self):
        m = KakaoMobilityMatrix(api_key="dummy")
        p = _place("A", 127.0, 37.5)
        assert m.get_travel_time(p, p) == 0


class TestApiCall:
    @patch("src.validation.kakao_matrix.requests.get")
    def test_first_call_hits_api_and_caches(self, mock_get, mock_response_ok):
        mock_get.return_value = mock_response_ok
        m = KakaoMobilityMatrix(api_key="dummy")

        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        result = m.get_travel_time(a, b)
        assert result == 600
        assert mock_get.call_count == 1
        assert m.stats["api_success"] == 1
        assert m.cache_size == 1

    @patch("src.validation.kakao_matrix.requests.get")
    def test_second_call_uses_cache(self, mock_get, mock_response_ok):
        mock_get.return_value = mock_response_ok
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        m.get_travel_time(a, b)
        m.get_travel_time(a, b)   # 두 번째 — 캐시 사용
        assert mock_get.call_count == 1
        assert m.stats["cache_hit"] == 1

    @patch("src.validation.kakao_matrix.requests.get")
    def test_reverse_direction_also_cached(self, mock_get, mock_response_ok):
        mock_get.return_value = mock_response_ok
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        m.get_travel_time(a, b)        # A→B 캐시 저장
        m.get_travel_time(b, a)        # B→A 도 같은 캐시 매칭

        assert mock_get.call_count == 1
        assert m.stats["cache_hit"] == 1


class TestQuotaExhaustion:
    @patch("src.validation.kakao_matrix.requests.get")
    def test_429_triggers_fallback(self, mock_get, mock_response_429):
        mock_get.return_value = mock_response_429
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)

        result = m.get_travel_time(a, b)
        # 폴백(haversine) 결과 — 0보다 큰 값
        assert result > 0
        assert m.is_quota_exhausted is True
        assert m.stats["fallback"] == 1

    @patch("src.validation.kakao_matrix.requests.get")
    def test_after_quota_no_more_api_calls(self, mock_get, mock_response_429):
        mock_get.return_value = mock_response_429
        m = KakaoMobilityMatrix(api_key="dummy")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)
        c = _place("C", 127.2, 37.7)

        m.get_travel_time(a, b)   # 한도 도달
        m.get_travel_time(a, c)   # API 호출 X

        # 첫 번째 호출만 API에 갔음
        assert mock_get.call_count == 1
        assert m.stats["fallback"] == 2


class TestAuthError:
    @patch("src.validation.kakao_matrix.requests.get")
    def test_401_raises(self, mock_get):
        m_resp = MagicMock(); m_resp.status_code = 401
        mock_get.return_value = m_resp
        m = KakaoMobilityMatrix(api_key="invalid")
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)
        with pytest.raises(RuntimeError, match="인증 오류"):
            m.get_travel_time(a, b)


class TestCachePersistence:
    @patch("src.validation.kakao_matrix.requests.get")
    def test_save_and_load_cache(self, mock_get, mock_response_ok, tmp_path):
        mock_get.return_value = mock_response_ok
        cache_file = tmp_path / "route_cache.json"

        # 1. 첫 인스턴스 — API 호출 + 캐시 저장
        m1 = KakaoMobilityMatrix(api_key="dummy", cache_path=cache_file, save_every=1)
        a = _place("A", 127.0, 37.5)
        b = _place("B", 127.1, 37.6)
        m1.get_travel_time(a, b)
        m1.save_cache()
        assert cache_file.exists()

        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert len(data) == 1

        # 2. 새 인스턴스 — 캐시 로드 후 API 호출 없이 동일 결과
        mock_get.reset_mock()
        m2 = KakaoMobilityMatrix(api_key="dummy", cache_path=cache_file)
        result = m2.get_travel_time(a, b)
        assert result == 600
        assert mock_get.call_count == 0
        assert m2.stats["cache_hit"] == 1


class TestFromEnv:
    def test_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("KAKAO_MOBILITY_KEY", raising=False)
        monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
        with pytest.raises(ValueError, match="API key 누락"):
            KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")

    def test_uses_mobility_key_first(self, monkeypatch):
        monkeypatch.setenv("KAKAO_MOBILITY_KEY", "MOBILITY_KEY")
        monkeypatch.setenv("KAKAO_REST_API_KEY", "REST_KEY")
        m = KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")
        assert m._api_key == "MOBILITY_KEY"

    def test_falls_back_to_rest_key(self, monkeypatch):
        monkeypatch.delenv("KAKAO_MOBILITY_KEY", raising=False)
        monkeypatch.setenv("KAKAO_REST_API_KEY", "REST_KEY")
        m = KakaoMobilityMatrix.from_env(env_path="/nonexistent/.env")
        assert m._api_key == "REST_KEY"
