"""한국관광공사 무장애 여행 정보 API 클라이언트 (B551011/KorWithService2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from src.data.models import Settings

_BASE_URL = "https://apis.data.go.kr/B551011/KorWithService2"
_LIST_OP = "getList"


@dataclass(frozen=True)
class BarrierFreePlace:
    content_id: str
    title: str
    addr: str
    lat: float
    lng: float
    wheelchair: bool = False     # 휠체어 접근 가능
    stroller: bool = False       # 유모차 접근 가능
    parking: bool = False        # 장애인 주차 가능
    elevator: bool = False       # 엘리베이터 있음
    guide_dog: bool = False      # 안내견 동반 가능


def _extract_items(data: dict) -> list[dict]:
    try:
        items = data["response"]["body"]["items"]["item"]
        if isinstance(items, dict):
            return [items]
        return list(items)
    except (KeyError, TypeError):
        return []


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _is_available(val: Any) -> bool:
    """API 응답의 Y/N 또는 1/0 값을 bool로 변환."""
    if val is None:
        return False
    s = str(val).strip().upper()
    return s in ("Y", "1", "TRUE", "가능")


class BarrierFreeAPIClient:
    """무장애 여행 정보 API — 비동기 클라이언트.

    Graceful Fallback: API 호출 실패 시 빈 리스트 반환.
    """

    def __init__(self, api_key: str, timeout_sec: float = 10.0) -> None:
        if not api_key:
            raise ValueError("barrier_free_api_key 없음. .env에 BARRIER_FREE_API_KEY를 설정하세요.")
        self._key = api_key
        self._timeout = timeout_sec

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "BarrierFreeAPIClient | None":
        if settings is None:
            settings = Settings()
        key = settings.barrier_free_api_key
        if not key:
            return None
        return cls(api_key=key)

    async def fetch_page(
        self,
        page_no: int = 1,
        num_of_rows: int = 100,
        area_code: str = "",
    ) -> list[BarrierFreePlace]:
        """무장애 여행 목록 한 페이지 조회."""
        params: dict[str, Any] = {
            "serviceKey": self._key,
            "numOfRows": num_of_rows,
            "pageNo": page_no,
            "MobileOS": "ETC",
            "MobileApp": "TravelQA",
            "_type": "json",
        }
        if area_code:
            params["areaCode"] = area_code

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{_BASE_URL}/{_LIST_OP}", params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        places: list[BarrierFreePlace] = []
        for item in _extract_items(data):
            content_id = str(item.get("contentid", "") or item.get("contentId", ""))
            title = str(item.get("title", ""))
            addr = str(item.get("addr1", "") or item.get("addr", ""))
            lat = _safe_float(item.get("mapy") or item.get("lat"))
            lng = _safe_float(item.get("mapx") or item.get("lng"))
            if not content_id or lat == 0.0 or lng == 0.0:
                continue
            places.append(BarrierFreePlace(
                content_id=content_id,
                title=title,
                addr=addr,
                lat=lat,
                lng=lng,
                wheelchair=_is_available(item.get("wheelchair") or item.get("handicapYn")),
                stroller=_is_available(item.get("stroller") or item.get("babyCarriageYn")),
                parking=_is_available(item.get("parking") or item.get("parkingLotYn")),
                elevator=_is_available(item.get("elevator") or item.get("elevatorYn")),
                guide_dog=_is_available(item.get("guideDog") or item.get("guideDogYn")),
            ))
        return places

    async def fetch_all(self, num_of_rows: int = 100) -> list[BarrierFreePlace]:
        """전체 무장애 여행 목록 조회 (페이지 순회)."""
        results: list[BarrierFreePlace] = []
        page = 1
        while True:
            page_items = await self.fetch_page(page_no=page, num_of_rows=num_of_rows)
            if not page_items:
                break
            results.extend(page_items)
            if len(page_items) < num_of_rows:
                break
            page += 1
        return results
