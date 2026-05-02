
"""
TourAPI v2 (KorService2) → CSV 벌크 수집 스크립트  [신 API 명세 v2 반영]
========================================================================
한국관광공사 국문 관광정보 서비스(data.go.kr 15101578) 호출 → CSV 저장.

신 명세 v2 주요 변경
--------------------
- 프로토콜: http → https
- 지역 필터: areaCode/sigunguCode (deprecated) → lDongRegnCd/lDongSignguCd (법정동)
- 분류 필터: cat1/cat2/cat3 (deprecated) → lclsSystm1/lclsSystm2/lclsSystm3
- 메타 엔드포인트: areaCode2 → lDongCode2, categoryCode2 → lclsSystmCode2
- 일일 트래픽: 엔드포인트당 1000회 (매우 빡빡 — 며칠 분산 수집 필요)

기능
----
1. ldongCode2로 시도/시군구/법정동(읍·면·동) 전체 수집 → ldong_codes.csv
2. lclsSystmCode2로 분류체계(1~3 Depth) 수집 → classification_codes.csv
3. areaBasedList2로 contentTypeId별 POI 마스터 수집 → pois.csv
4. (선택) detailIntro2로 운영시간 enrich → operating_hours.csv
5. (선택) searchFestival2로 축제 일정 + 기간 수집 → festivals.csv
6. 일일 호출 한도 추적 + 자동 종료 (실수로 한도 초과 방지)
7. 체크포인트 기반 resume — 다음 날 이어서 계속

실행
----
    # .env에 TOUR_API_KEY 설정 필수
    python scripts/fetch_tourapi_to_csv.py --test                    # 인증/연결 테스트
    python scripts/fetch_tourapi_to_csv.py --meta-only               # 코드 메타 먼저 받기
    python scripts/fetch_tourapi_to_csv.py --types 12 --skip-meta    # 관광지만 수집
    python scripts/fetch_tourapi_to_csv.py --types 14,15 --skip-meta # 문화시설+축제
    python scripts/fetch_tourapi_to_csv.py --enrich-hours            # 운영시간 보강
    python scripts/fetch_tourapi_to_csv.py --festivals               # 축제 일정 (2022~2025)
    python scripts/fetch_tourapi_to_csv.py --festivals \\
        --festival-start 20240101 --festival-end 20241231            # 2024년 축제만
    python scripts/fetch_tourapi_to_csv.py --reset                   # 처음부터 다시

산출물
------
    data/
      ├─ pois.csv                  # 메인 POI 마스터
      ├─ operating_hours.csv       # detailIntro2 운영시간 (옵션)
      ├─ festivals.csv             # 축제 일정 + 기간 (옵션)
      ├─ ldong_codes.csv           # 법정동 시도/시군구/법정동 전체
      ├─ classification_codes.csv  # 분류체계 1~3 Depth
      └─ _checkpoint.json          # 진행 상태 + 일일 호출 카운트
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import requests

# ── 0. 설정 ──────────────────────────────────────────────────────────
BASE_URL = "https://apis.data.go.kr/B551011/KorService2"   # HTTPS

# contentTypeId 정의 (TourAPI v2 기준)
CONTENT_TYPES: dict[int, str] = {
    12: "관광지",
    14: "문화시설",
    15: "축제공연행사",
    25: "여행코스",
    28: "레포츠",
    32: "숙박",
    38: "쇼핑",
    39: "음식점",
}

# CSV 컬럼 (areaBasedList2 v2 응답 기준)
POI_COLUMNS = [
    "contentid", "contenttypeid", "title",
    "addr1", "addr2", "zipcode",
    "lDongRegnCd", "lDongSignguCd",       # 법정동 시도/시군구
    "lclsSystm1", "lclsSystm2", "lclsSystm3",   # 분류체계 1~3 Depth
    "mapx", "mapy", "mlevel",
    "tel",
    "firstimage", "firstimage2",
    "cpyrhtDivCd",
    "createdtime", "modifiedtime",
]

# detailIntro2 응답 키는 contentTypeId마다 다름
# 운영시간 관련 핵심 필드만 추출 (대부분 contentTypeId에 공통/유사)
INTRO_COLUMNS = [
    "contentid", "contenttypeid",
    "usetime",     # 이용시간 (관광지/레포츠/문화시설)
    "opentime",    # 개장시간
    "opendate",    # 개장일
    "restdate",    # 쉬는날
    "infocenter",  # 문의·안내
    "parking",     # 주차시설
]

# searchFestival2 응답 — 축제 전용 (eventstartdate/eventenddate 포함)
FESTIVAL_COLUMNS = [
    "contentid", "contenttypeid", "title",
    "addr1", "addr2", "zipcode",
    "lDongRegnCd", "lDongSignguCd",
    "lclsSystm1", "lclsSystm2", "lclsSystm3",
    "mapx", "mapy", "mlevel",
    "tel",
    "eventstartdate", "eventenddate",   # 핵심: 축제 기간
    "firstimage", "firstimage2",
    "cpyrhtDivCd",
    "createdtime", "modifiedtime",
]

# 한국 좌표 경계 (오매핑 검증용)
KR_LAT = (33.0, 38.7)
KR_LON = (124.5, 132.0)

# API 호출 정책 (신 명세 1000회/일 반영)
NUM_OF_ROWS = 100              # 페이지당 최대 100
SLEEP_BETWEEN_CALLS = 0.15     # 초당 ~6회 호출
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0            # 1차 2s, 2차 4s, 3차 8s
DAILY_LIMIT = 1000             # 엔드포인트당 일일 한도
DAILY_SAFETY_MARGIN = 50       # 한도까지 50회 남으면 자동 종료

# __file__은 파일로 실행 시에만 정의됨. 인터랙티브(VS Code Run Selection 등)에서는
# 정의되지 않으므로 폴백으로 cwd 또는 sys.argv[0]을 사용.
def _resolve_base_dir() -> Path:
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:
        # 인터랙티브 모드: cwd가 프로젝트 루트라고 가정
        cwd = Path.cwd()
        # cwd가 scripts/ 디렉토리면 한 단계 상위로
        if cwd.name == "scripts":
            return cwd.parent
        return cwd

BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

POIS_CSV          = DATA_DIR / "pois.csv"
OPERATING_CSV     = DATA_DIR / "operating_hours.csv"
FESTIVALS_CSV     = DATA_DIR / "festivals.csv"          # 신규: 축제 일정
LDONG_CSV         = DATA_DIR / "ldong_codes.csv"
CLASSIFICATION_CSV= DATA_DIR / "classification_codes.csv"
CHECKPOINT_FILE   = DATA_DIR / "_checkpoint.json"


# ── 1. 환경변수 로드 (analyze.py와 동일 방식) ─────────────────────────
def load_env() -> str:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    key = os.environ.get("TOUR_API_KEY", "")
    if not key:
        sys.exit(
            "[error] TOUR_API_KEY 환경변수가 설정되지 않았습니다.\n"
            "  → .env 파일에 다음 줄을 추가하세요:\n"
            "       TOUR_API_KEY=<발급받은 일반 인증키 (Decoding 키)>"
        )
    return key


# ── 2. 체크포인트 ────────────────────────────────────────────────────
@dataclass
class Checkpoint:
    """수집 진행 상태 + 일일 호출 카운트.
    엔드포인트별 호출 수를 날짜와 함께 기록 → 일일 한도 추적."""
    done_keys: set[str] = field(default_factory=set)
    seen_contentids: set[str] = field(default_factory=set)
    enriched_contentids: set[str] = field(default_factory=set)
    # endpoint별 일일 호출 카운트: {"areaBasedList2": {"date": "YYYY-MM-DD", "count": 123}}
    daily_calls: dict[str, dict] = field(default_factory=dict)
    started_at: str = ""

    @classmethod
    def load(cls) -> "Checkpoint":
        if CHECKPOINT_FILE.exists():
            d = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
            return cls(
                done_keys=set(d.get("done_keys", [])),
                seen_contentids=set(d.get("seen_contentids", [])),
                enriched_contentids=set(d.get("enriched_contentids", [])),
                daily_calls=d.get("daily_calls", {}),
                started_at=d.get("started_at", ""),
            )
        return cls(started_at=time.strftime("%Y-%m-%d %H:%M:%S"))

    def save(self) -> None:
        CHECKPOINT_FILE.write_text(
            json.dumps({
                "done_keys": sorted(self.done_keys),
                "seen_contentids": sorted(self.seen_contentids),
                "enriched_contentids": sorted(self.enriched_contentids),
                "daily_calls": self.daily_calls,
                "started_at": self.started_at,
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def increment_daily(self, endpoint: str) -> int:
        today = date.today().isoformat()
        rec = self.daily_calls.get(endpoint, {})
        if rec.get("date") != today:
            rec = {"date": today, "count": 0}
        rec["count"] += 1
        self.daily_calls[endpoint] = rec
        return rec["count"]

    def remaining_today(self, endpoint: str) -> int:
        today = date.today().isoformat()
        rec = self.daily_calls.get(endpoint, {})
        if rec.get("date") != today:
            return DAILY_LIMIT
        return max(0, DAILY_LIMIT - rec.get("count", 0))

    def key(self, content_type: int, ldong: str | None, page_no: int) -> str:
        return f"{content_type}|{ldong or 'ALL'}|{page_no}"

    def is_done(self, content_type: int, ldong: str | None, page_no: int) -> bool:
        return self.key(content_type, ldong, page_no) in self.done_keys

    def mark_done(self, content_type: int, ldong: str | None, page_no: int) -> None:
        self.done_keys.add(self.key(content_type, ldong, page_no))


# ── 3. HTTP 호출 (재시도 + 일일 한도 체크) ────────────────────────────
class DailyLimitReached(Exception):
    """일일 한도 도달 — 체크포인트 저장 후 정상 종료."""


def call_api(
    endpoint: str,
    params: dict[str, Any],
    service_key: str,
    checkpoint: Checkpoint | None = None,
) -> dict | None:
    """TourAPI 호출. 실패 시 None. 한도 도달 시 DailyLimitReached."""

    # 일일 한도 사전 체크
    if checkpoint is not None:
        remaining = checkpoint.remaining_today(endpoint)
        if remaining <= DAILY_SAFETY_MARGIN:
            raise DailyLimitReached(
                f"{endpoint} 일일 한도 임박 (잔여 {remaining}회 ≤ 안전 마진 {DAILY_SAFETY_MARGIN})"
            )

    full_params = {
        "serviceKey": service_key,
        "MobileOS": "ETC",
        "MobileApp": "TravelValidator",
        "_type": "json",
        **params,
    }
    url = f"{BASE_URL}/{endpoint}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, params=full_params, timeout=10)
            if checkpoint is not None:
                checkpoint.increment_daily(endpoint)

            if r.status_code == 200:
                try:
                    data = r.json()
                except json.JSONDecodeError:
                    # XML 에러 응답일 가능성 (인증 실패 등)
                    print(f"  [warn] JSON 파싱 실패 ({endpoint}): {r.text[:300]}")
                    if "SERVICE_KEY" in r.text or "SERVICE KEY" in r.text:
                        sys.exit("[fatal] 인증키 오류 — TOUR_API_KEY를 확인하세요 "
                                 "(Decoding 키 사용 권장).")
                    return None

                # 정상 응답 구조: response.header.resultCode = "0000"
                header = data.get("response", {}).get("header", {})
                code = header.get("resultCode", "")
                if code == "0000":
                    return data

                # 오류 응답이 OpenAPI_ServiceResponse 래퍼로 오는 경우 처리
                err_wrap = data.get("OpenAPI_ServiceResponse", {})
                if err_wrap:
                    err_hdr = err_wrap.get("cmmMsgHeader", {})
                    code = err_hdr.get("returnReasonCode", code)
                    msg = err_hdr.get("returnAuthMsg") or err_hdr.get("errMsg", "")
                else:
                    msg = header.get("resultMsg", "")

                # 둘 다 비었으면 응답 본문을 그대로 출력 (디버그)
                if not code and not msg:
                    print(f"  [api error] 알 수 없는 응답 구조 ({endpoint})")
                    print(f"    응답 본문: {json.dumps(data, ensure_ascii=False)[:500]}")
                    return None

                print(f"  [api error] code={code} msg={msg} ({endpoint} {params})")
                # 일일 한도 초과 (코드 22)
                if code == "22" or "LIMITED" in str(msg).upper():
                    raise DailyLimitReached(f"{endpoint} 한도 초과 응답: {msg}")
                # 인증 실패 (코드 30/31)
                if str(code) in ("30", "31"):
                    sys.exit(f"[fatal] 인증 오류 {code}: {msg}\n"
                             f"  → data.go.kr에서 키 발급 후 1~2시간 활성화 대기 / "
                             f"Decoding 키 사용 확인")
                return None

            elif r.status_code == 429:
                wait = RETRY_BACKOFF ** attempt
                print(f"  [429] {wait}초 대기 후 재시도...")
                time.sleep(wait)
            else:
                print(f"  [http {r.status_code}] {endpoint}")
                return None
        except requests.RequestException as e:
            wait = RETRY_BACKOFF ** attempt
            print(f"  [retry {attempt}/{MAX_RETRIES}] {e} — {wait}초 대기")
            time.sleep(wait)

    return None


def parse_items(api_response: dict) -> list[dict]:
    """API 응답에서 items.item 리스트 추출. 빈 응답 안전 처리."""
    body = api_response.get("response", {}).get("body", {})
    items = body.get("items")
    if not items or items == "":
        return []
    item = items.get("item")
    if not item:
        return []
    return [item] if isinstance(item, dict) else item


def get_total_count(api_response: dict) -> int:
    body = api_response.get("response", {}).get("body", {})
    return int(body.get("totalCount", 0))


# ── 4. CSV 저장 (append + 헤더 자동 감지) ─────────────────────────────
class CsvAppender:
    def __init__(self, path: Path, columns: list[str]):
        self.path = path
        self.columns = columns
        self._file = None
        self._writer = None

    def __enter__(self):
        is_new = not self.path.exists()
        self._file = open(self.path, "a", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=self.columns,
                                      extrasaction="ignore")
        if is_new:
            self._writer.writeheader()
        return self

    def __exit__(self, *exc):
        if self._file:
            self._file.close()

    def write(self, row: dict) -> None:
        self._writer.writerow(row)

    def write_many(self, rows: Iterable[dict]) -> None:
        self._writer.writerows(rows)


# ── 5. 좌표 검증 ──────────────────────────────────────────────────────
def is_valid_kr_coord(mapx: str, mapy: str) -> bool:
    try:
        lon, lat = float(mapx), float(mapy)
        return KR_LAT[0] <= lat <= KR_LAT[1] and KR_LON[0] <= lon <= KR_LON[1]
    except (ValueError, TypeError):
        return False


# ── 6. 메타데이터 수집 — ldongCode2 (법정동 시도/시군구/법정동 전체) ──
# ⚠ 엔드포인트 경로는 **소문자** ldongCode2. 파라미터(lDongRegnCd)와 케이스가 다름.
LDONG_ENDPOINT = "ldongCode2"

def fetch_ldong_codes(service_key: str, checkpoint: Checkpoint) -> None:
    """ldongCode2로 전체 법정동(시도+시군구+법정동) 수집.
    lDongListYn=Y 옵션으로 전체 목록 조회 + 페이지네이션."""
    print(f"\n[meta 1/2] 법정동 코드({LDONG_ENDPOINT}) 수집 중...")

    rows: list[dict] = []

    # ─ 1단계: 시도 + 시군구 (계층 정보 정확히 보존)
    print("  - 시도 + 시군구 계층 수집...")
    resp = call_api(
        LDONG_ENDPOINT,
        {"numOfRows": 100, "pageNo": 1, "lDongListYn": "N"},
        service_key, checkpoint,
    )
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not resp:
        print("  [skip] 시도 코드 조회 실패")
        return

    sidos = parse_items(resp)
    for sido in sidos:
        sido_code = sido.get("code") or sido.get("lDongRegnCd")
        sido_name = sido.get("name") or sido.get("lDongRegnNm")
        rows.append({
            "level": 1, "code": sido_code, "name": sido_name, "parent_code": "",
            "full_code": sido_code,
        })
        sub = call_api(
            LDONG_ENDPOINT,
            {"lDongRegnCd": sido_code, "numOfRows": 100, "pageNo": 1, "lDongListYn": "N"},
            service_key, checkpoint,
        )
        time.sleep(SLEEP_BETWEEN_CALLS)
        if sub:
            for sigungu in parse_items(sub):
                sg_code = sigungu.get("code") or sigungu.get("lDongSignguCd")
                rows.append({
                    "level": 2,
                    "code": sg_code,
                    "name": sigungu.get("name") or sigungu.get("lDongSignguNm"),
                    "parent_code": sido_code,
                    "full_code": f"{sido_code}{sg_code}",
                })

    # ─ 2단계: 법정동(읍/면/동) 전체 — per-sigungu 순회 방식
    #   이전 방식(lDongListYn=Y 단독)이 264건에서 멈추는 버그 → 시군구별로 호출
    #   호출 비용: 시군구 수 만큼 (~264회) — 일일 한도 1000회 안에서 충분
    print("  - 법정동(읍/면/동) 시군구별 수집 (시간 소요)...")
    sigungus = [r for r in rows if r["level"] == 2]
    total_sg = len(sigungus)
    ldong_rows = 0

    for sg_idx, sg in enumerate(sigungus, 1):
        sido_code = sg["parent_code"]
        sg_code = sg["code"]

        # 한 시군구의 법정동 페이지네이션 (보통 1~2페이지면 충분)
        page = 1
        while True:
            resp = call_api(
                LDONG_ENDPOINT,
                {
                    "lDongRegnCd": sido_code,
                    "lDongSignguCd": sg_code,
                    "lDongListYn": "Y",
                    "numOfRows": 1000,
                    "pageNo": page,
                },
                service_key, checkpoint,
            )
            time.sleep(SLEEP_BETWEEN_CALLS)
            if not resp:
                break
            items = parse_items(resp)
            if not items:
                break

            for it in items:
                ld_code = it.get("lDongCd") or it.get("code")
                ld_name = it.get("lDongNm") or it.get("name")
                if not ld_code:
                    continue
                rows.append({
                    "level": 3,
                    "code": ld_code,
                    "name": ld_name,
                    "parent_code": f"{sido_code}{sg_code}",
                    "full_code": f"{sido_code}{sg_code}{ld_code}",
                })
                ldong_rows += 1

            total = get_total_count(resp)
            last_page = (total + 1000 - 1) // 1000
            if page >= last_page:
                break
            page += 1

        if sg_idx % 30 == 0:
            print(f"    [progress] {sg_idx}/{total_sg} 시군구 완료 "
                  f"(누적 법정동 {ldong_rows}건)")

    with open(LDONG_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "code", "name", "parent_code", "full_code"])
        w.writeheader()
        w.writerows(rows)
    sido_n = sum(1 for r in rows if r["level"] == 1)
    sg_n   = sum(1 for r in rows if r["level"] == 2)
    ld_n   = sum(1 for r in rows if r["level"] == 3)
    print(f"  → {LDONG_CSV.name} 저장 (시도 {sido_n} / 시군구 {sg_n} / 법정동 {ld_n}건)")


# ── 7. 메타데이터 수집 — lclsSystmCode2 (분류체계 1~3 Depth) ──────────
def fetch_classification_codes(service_key: str, checkpoint: Checkpoint) -> None:
    """lclsSystmCode2 → 분류체계 1~3 Depth 트리 수집."""
    print("\n[meta 2/2] 분류체계(lclsSystmCode2) 수집 중...")

    rows: list[dict] = []

    # 1Depth (대분류) — 파라미터 없이 호출, lclsSystmListYn=N
    resp = call_api(
        "lclsSystmCode2",
        {"numOfRows": 100, "pageNo": 1, "lclsSystmListYn": "N"},
        service_key, checkpoint,
    )
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not resp:
        print("  [skip] 1Depth 조회 실패")
        return

    cat1_list = parse_items(resp)
    for c1 in cat1_list:
        c1_code = c1.get("code") or c1.get("lclsSystm1Cd")
        c1_name = c1.get("name") or c1.get("lclsSystm1Nm")
        rows.append({"level": 1, "code": c1_code, "name": c1_name, "parent_code": ""})

        # 2Depth — lclsSystm1=대분류
        c2_resp = call_api(
            "lclsSystmCode2",
            {"lclsSystm1": c1_code, "numOfRows": 100, "pageNo": 1, "lclsSystmListYn": "N"},
            service_key, checkpoint,
        )
        time.sleep(SLEEP_BETWEEN_CALLS)
        if not c2_resp:
            continue

        for c2 in parse_items(c2_resp):
            c2_code = c2.get("code") or c2.get("lclsSystm2Cd")
            c2_name = c2.get("name") or c2.get("lclsSystm2Nm")
            rows.append({"level": 2, "code": c2_code, "name": c2_name, "parent_code": c1_code})

            # 3Depth — lclsSystm1, lclsSystm2 둘 다 필요
            c3_resp = call_api(
                "lclsSystmCode2",
                {"lclsSystm1": c1_code, "lclsSystm2": c2_code,
                 "numOfRows": 100, "pageNo": 1, "lclsSystmListYn": "N"},
                service_key, checkpoint,
            )
            time.sleep(SLEEP_BETWEEN_CALLS)
            if not c3_resp:
                continue
            for c3 in parse_items(c3_resp):
                c3_code = c3.get("code") or c3.get("lclsSystm3Cd")
                c3_name = c3.get("name") or c3.get("lclsSystm3Nm")
                rows.append({"level": 3, "code": c3_code, "name": c3_name,
                             "parent_code": c2_code})

    with open(CLASSIFICATION_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["level", "code", "name", "parent_code"])
        w.writeheader()
        w.writerows(rows)
    print(f"  → {CLASSIFICATION_CSV.name} 저장 ({len(rows)}건)")


# ── 8. 메인 수집 — areaBasedList2 ────────────────────────────────────
def fetch_pois(
    service_key: str,
    content_types: list[int],
    ldong_codes: list[str | None],
    checkpoint: Checkpoint,
    modifiedtime: str | None = None,
) -> None:
    """contentTypeId × lDongRegnCd 조합으로 페이지네이션 순회.
    modifiedtime: 'YYYYMMDD' — 해당 날짜 이후 수정된 항목만 (예: '20220101' = 2022~)."""
    print(f"\n[POI] areaBasedList2 수집 중... "
          f"types={content_types}, regions={ldong_codes}, modifiedtime≥{modifiedtime}")

    written = invalid = duplicate = 0

    with CsvAppender(POIS_CSV, POI_COLUMNS) as csv_out:
        for ct in content_types:
            ct_name = CONTENT_TYPES.get(ct, str(ct))
            for ld in ldong_codes:
                ld_label = f"lDongRegnCd={ld}" if ld else "전국"
                params = {
                    "contentTypeId": ct,
                    "numOfRows": NUM_OF_ROWS,
                    "pageNo": 1,
                    "arrange": "C",     # 수정일순 (안정적)
                    # showflag 는 신 명세에서 거부됨(INVALID_REQUEST_PARAMETER_ERROR) — 제거
                }
                if ld is not None:
                    params["lDongRegnCd"] = ld
                # ⚠ modifiedtime은 areaBasedList2에서 의도대로 동작 안 함
                #   ('이후' 필터가 아닌 '정확히 그 날짜'로 해석됨 → total=0)
                #   날짜 필터링은 (1) 수집 후 CSV의 modifiedtime 컬럼으로 pandas 필터,
                #                또는 (2) areaBasedSyncList2 별도 사용 권장.
                #   인자 modifiedtime은 향후 areaBasedSyncList2 마이그레이션용으로 보존.
                _ = modifiedtime  # noqa: F841 (의도적 미사용)

                # 첫 페이지로 totalCount 확인
                first = call_api("areaBasedList2", params, service_key, checkpoint)
                time.sleep(SLEEP_BETWEEN_CALLS)
                if not first:
                    print(f"  [skip] {ct_name}/{ld_label} 첫 페이지 실패")
                    continue

                total = get_total_count(first)
                last_page = (total + NUM_OF_ROWS - 1) // NUM_OF_ROWS
                rem = checkpoint.remaining_today("areaBasedList2")
                print(f"  ▷ {ct_name}({ct}) / {ld_label}: total={total}, "
                      f"pages=1~{last_page} (오늘 잔여 {rem}회)")

                # 1페이지 처리
                if not checkpoint.is_done(ct, ld, 1):
                    w, i, d = _process_items(parse_items(first), csv_out, checkpoint)
                    written += w; invalid += i; duplicate += d
                    checkpoint.mark_done(ct, ld, 1)

                # 2페이지부터
                for page in range(2, last_page + 1):
                    if checkpoint.is_done(ct, ld, page):
                        continue
                    params["pageNo"] = page
                    resp = call_api("areaBasedList2", params, service_key, checkpoint)
                    time.sleep(SLEEP_BETWEEN_CALLS)
                    if not resp:
                        print(f"    [page {page}] 실패 — 다음 실행에서 재시도")
                        checkpoint.save()
                        continue

                    w, i, d = _process_items(parse_items(resp), csv_out, checkpoint)
                    written += w; invalid += i; duplicate += d
                    checkpoint.mark_done(ct, ld, page)

                    # 50페이지마다 체크포인트 저장
                    if page % 50 == 0:
                        checkpoint.save()
                        rem = checkpoint.remaining_today("areaBasedList2")
                        print(f"    [progress] page {page}/{last_page} "
                              f"(누적 신규 {written}건, 오늘 잔여 {rem}회)")

                checkpoint.save()
                print(f"  ✓ {ct_name}/{ld_label} 완료")

    print(f"\n[완료] 신규 {written}건 / 좌표오류 {invalid}건 / 중복 {duplicate}건")


def _process_items(
    items: list[dict],
    csv_out: CsvAppender,
    checkpoint: Checkpoint,
) -> tuple[int, int, int]:
    """페이지의 item을 검증 + CSV에 쓰기. 반환: (저장, 좌표오류, 중복)."""
    written = invalid = duplicate = 0
    for item in items:
        cid = str(item.get("contentid", ""))
        if not cid:
            continue
        if cid in checkpoint.seen_contentids:
            duplicate += 1
            continue
        if not is_valid_kr_coord(item.get("mapx", ""), item.get("mapy", "")):
            invalid += 1
            continue
        row = {col: item.get(col, "") for col in POI_COLUMNS}
        csv_out.write(row)
        checkpoint.seen_contentids.add(cid)
        written += 1
    return written, invalid, duplicate


# ── 9. 축제 일정 수집 — searchFestival2 ───────────────────────────────
def fetch_festivals(
    service_key: str,
    checkpoint: Checkpoint,
    event_start: str = "20220101",
    event_end: str = "20251231",
) -> None:
    """searchFestival2로 [event_start, event_end] 기간의 축제 일정 수집.
    eventStartDate 필터로 해당 날짜 이후 시작하는 축제 + eventEndDate로 상한 적용.

    인자
    ----
    event_start : YYYYMMDD — 행사 시작일 (이상)
    event_end   : YYYYMMDD — 행사 종료일 (이하), 빈 문자열이면 미적용
    """
    print(f"\n[festivals] searchFestival2 수집 중... "
          f"기간 {event_start} ~ {event_end or '미지정'}")

    # 첫 페이지로 totalCount 확인
    base_params = {
        "numOfRows": NUM_OF_ROWS,
        "pageNo": 1,
        "arrange": "C",
        "eventStartDate": event_start,
    }
    if event_end:
        base_params["eventEndDate"] = event_end

    first = call_api("searchFestival2", base_params, service_key, checkpoint)
    time.sleep(SLEEP_BETWEEN_CALLS)
    if not first:
        print("  [skip] 첫 페이지 실패")
        return

    total = get_total_count(first)
    last_page = (total + NUM_OF_ROWS - 1) // NUM_OF_ROWS
    rem = checkpoint.remaining_today("searchFestival2")
    print(f"  ▷ total={total}, pages=1~{last_page} (오늘 잔여 {rem}회)")

    written = invalid = duplicate = 0
    seen_festival_ids: set[str] = set()

    def _process_festival_items(items: list[dict], csv_out: CsvAppender) -> None:
        nonlocal written, invalid, duplicate
        for item in items:
            cid = str(item.get("contentid", ""))
            if not cid or cid in seen_festival_ids:
                duplicate += 1
                continue
            # 좌표가 없는 축제는 종종 있음 — 좌표 검증을 약간 완화
            mapx = item.get("mapx", "")
            mapy = item.get("mapy", "")
            if mapx and mapy and not is_valid_kr_coord(mapx, mapy):
                invalid += 1
                continue
            row = {col: item.get(col, "") for col in FESTIVAL_COLUMNS}
            csv_out.write(row)
            seen_festival_ids.add(cid)
            written += 1

    with CsvAppender(FESTIVALS_CSV, FESTIVAL_COLUMNS) as csv_out:
        # 1페이지 처리
        _process_festival_items(parse_items(first), csv_out)

        # 2페이지부터
        for page in range(2, last_page + 1):
            base_params["pageNo"] = page
            resp = call_api("searchFestival2", base_params, service_key, checkpoint)
            time.sleep(SLEEP_BETWEEN_CALLS)
            if not resp:
                print(f"    [page {page}] 실패 — 다음 실행에서 재시도")
                continue
            _process_festival_items(parse_items(resp), csv_out)

            if page % 20 == 0:
                rem = checkpoint.remaining_today("searchFestival2")
                print(f"    [progress] page {page}/{last_page} "
                      f"(누적 신규 {written}건, 오늘 잔여 {rem}회)")

    print(f"\n[festivals 완료] 신규 {written}건 / 좌표오류 {invalid}건 / 중복 {duplicate}건")
    print(f"  → {FESTIVALS_CSV.name} 저장")


# ── 10. 운영시간 enrich — detailIntro2 ───────────────────────────────
def enrich_operating_hours(service_key: str, checkpoint: Checkpoint) -> None:
    """pois.csv를 읽어 detailIntro2로 운영시간 보강.
    이미 enriched된 contentid는 스킵."""
    print("\n[enrich] detailIntro2로 운영시간 수집 중...")

    if not POIS_CSV.exists():
        sys.exit(f"[error] {POIS_CSV} 없음 — 먼저 POI 수집 실행 필요")

    # pois.csv에서 contentid + contenttypeid 로드
    pois: list[tuple[str, str]] = []
    with open(POIS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cid = row.get("contentid", "").strip()
            ctid = row.get("contenttypeid", "").strip()
            if cid and ctid and cid not in checkpoint.enriched_contentids:
                pois.append((cid, ctid))

    rem = checkpoint.remaining_today("detailIntro2")
    print(f"  대상: {len(pois)}개 (오늘 잔여 호출 {rem}회)")

    written = 0
    with CsvAppender(OPERATING_CSV, INTRO_COLUMNS) as csv_out:
        for cid, ctid in pois:
            try:
                resp = call_api(
                    "detailIntro2",
                    {"contentId": cid, "contentTypeId": ctid,
                     "numOfRows": 10, "pageNo": 1},
                    service_key, checkpoint,
                )
            except DailyLimitReached as e:
                print(f"  [한도] {e} — 내일 --enrich-hours 로 이어가세요")
                break

            time.sleep(SLEEP_BETWEEN_CALLS)
            if not resp:
                continue

            items = parse_items(resp)
            if not items:
                checkpoint.enriched_contentids.add(cid)
                continue

            row = {col: items[0].get(col, "") for col in INTRO_COLUMNS}
            row["contentid"] = cid
            row["contenttypeid"] = ctid
            csv_out.write(row)
            checkpoint.enriched_contentids.add(cid)
            written += 1

            if written % 50 == 0:
                checkpoint.save()
                print(f"  [progress] {written}건 enrich (오늘 잔여 "
                      f"{checkpoint.remaining_today('detailIntro2')}회)")

    print(f"\n[enrich 완료] {written}건 운영시간 추가")


# ── 10. 인증 테스트 ───────────────────────────────────────────────────
def test_connection(service_key: str) -> None:
    """1회 호출로 인증/연결 검증."""
    print("\n[test] 인증·연결 테스트 중...")
    resp = call_api(
        "areaBasedList2",
        {"contentTypeId": 12, "numOfRows": 1, "pageNo": 1, "arrange": "C"},
        service_key, checkpoint=None,
    )
    if not resp:
        sys.exit("[FAIL] 응답 없음 — 인증키/네트워크 확인 필요")

    body = resp.get("response", {}).get("body", {})
    total = body.get("totalCount", 0)
    items = parse_items(resp)
    sample = items[0] if items else {}
    print(f"[OK] 연결 정상")
    print(f"  관광지 totalCount = {total}")
    if sample:
        print(f"  샘플 1건: {sample.get('title')} "
              f"({sample.get('lDongRegnCd')}-{sample.get('lDongSignguCd')}) "
              f"{sample.get('mapx')}, {sample.get('mapy')}")


# ── 11. 엔트리 포인트 ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="TourAPI v2 벌크 수집 → CSV (신 명세 v2)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--types", default="",
        help=f"수집할 contentTypeId 콤마 구분 (기본: 전체)\n"
             f"  {', '.join(f'{k}={v}' for k, v in CONTENT_TYPES.items())}",
    )
    parser.add_argument(
        "--ldong", default="",
        help="특정 lDongRegnCd만 수집 (예: --ldong 11 = 서울특별시).\n"
             "지정 없으면 전국 일괄.",
    )
    parser.add_argument(
        "--split-by-region", action="store_true",
        help="시도별로 분할 호출 (ldong_codes.csv 필요).",
    )
    parser.add_argument("--reset", action="store_true",
                        help="체크포인트 + CSV 삭제 후 처음부터")
    parser.add_argument("--meta-only", action="store_true",
                        help="ldong/classification 메타만 수집")
    parser.add_argument("--skip-meta", action="store_true",
                        help="메타 스킵, POI만 수집")
    parser.add_argument("--enrich-hours", action="store_true",
                        help="detailIntro2로 운영시간 보강 (pois.csv 필요)")
    parser.add_argument("--festivals", action="store_true",
                        help="searchFestival2로 축제 일정 수집 → festivals.csv")
    parser.add_argument("--festival-start", default="20220101",
                        help="축제 시작일 필터 (YYYYMMDD, 기본 20220101)")
    parser.add_argument("--festival-end", default="20251231",
                        help="축제 종료일 필터 (YYYYMMDD, 기본 20251231). "
                             "빈 문자열로 두면 종료일 제한 없음.")
    parser.add_argument("--test", action="store_true",
                        help="1회 호출 테스트 후 종료 (인증/연결 확인)")
    parser.add_argument(
        "--from-year", default="",
        help="(deprecated) areaBasedList2의 modifiedtime 필터는 신 API에서 동작 X. "
             "수집 후 CSV의 modifiedtime 컬럼으로 pandas 필터링 권장. "
             "옵션 자체는 향후 areaBasedSyncList2 사용을 위해 보존.",
    )
    args = parser.parse_args()

    service_key = load_env()

    # ─ 1회 테스트
    if args.test:
        test_connection(service_key)
        return

    # ─ Reset
    if args.reset:
        for f in [POIS_CSV, OPERATING_CSV, CHECKPOINT_FILE]:
            if f.exists():
                f.unlink()
                print(f"[reset] {f.name} 삭제")

    checkpoint = Checkpoint.load()
    print(f"[checkpoint] 진행: {len(checkpoint.done_keys)}페이지 완료, "
          f"{len(checkpoint.seen_contentids)} unique POI 보유")
    print(f"[daily] 오늘 호출 한도 (각 엔드포인트당 {DAILY_LIMIT}회):")
    for ep, rec in checkpoint.daily_calls.items():
        if rec.get("date") == date.today().isoformat():
            print(f"  - {ep}: {rec['count']}/{DAILY_LIMIT}회 사용")

    try:
        # ─ 축제 일정 수집 모드 (단독 실행)
        if args.festivals:
            fetch_festivals(
                service_key, checkpoint,
                event_start=args.festival_start,
                event_end=args.festival_end,
            )
            return

        # ─ 운영시간 보강 모드
        if args.enrich_hours:
            enrich_operating_hours(service_key, checkpoint)
            return

        # ─ 메타데이터
        if not args.skip_meta:
            fetch_ldong_codes(service_key, checkpoint)
            fetch_classification_codes(service_key, checkpoint)

        if args.meta_only:
            print("\n[done] --meta-only 옵션으로 메타만 수집 완료.")
            return

        # ─ 수집 대상 결정
        if args.types:
            content_types = [int(x) for x in args.types.split(",") if x.strip()]
        else:
            content_types = list(CONTENT_TYPES.keys())

        if args.ldong:
            ldong_codes: list[str | None] = [args.ldong]
        elif args.split_by_region:
            if not LDONG_CSV.exists():
                sys.exit("[error] --split-by-region 사용하려면 ldong_codes.csv 먼저 필요 "
                         "(--meta-only 로 받으세요).")
            ldong_codes = []
            with open(LDONG_CSV, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    if int(row.get("level", 0)) == 1:
                        ldong_codes.append(row["code"])
            print(f"[split] 시도 {len(ldong_codes)}개로 분할 수집")
        else:
            ldong_codes = [None]

        # modifiedtime 파라미터 변환 (YYYY → YYYY0101)
        modifiedtime = None
        if args.from_year and args.from_year.strip():
            yr = args.from_year.strip()
            if len(yr) == 4 and yr.isdigit():
                modifiedtime = f"{yr}0101"
            elif len(yr) == 8 and yr.isdigit():
                modifiedtime = yr  # 이미 YYYYMMDD 형식
            else:
                sys.exit(f"[error] --from-year 형식 오류: {yr} (예: 2022 또는 20220101)")

        fetch_pois(service_key, content_types, ldong_codes, checkpoint, modifiedtime)

    except DailyLimitReached as e:
        print(f"\n[일일 한도] {e}")
        print("  → 내일 같은 명령어를 다시 실행하면 체크포인트 이후부터 이어집니다.")
    except KeyboardInterrupt:
        print("\n[중단] Ctrl+C — 체크포인트 저장 후 종료")
    finally:
        checkpoint.save()
        print(f"\n[summary]")
        for ep, rec in checkpoint.daily_calls.items():
            if rec.get("date") == date.today().isoformat():
                print(f"  {ep}: {rec['count']}/{DAILY_LIMIT}회")
        print(f"  unique contentid: {len(checkpoint.seen_contentids)}개")
        print(f"  체크포인트: {CHECKPOINT_FILE}")
        if POIS_CSV.exists():
            print(f"  POI CSV: {POIS_CSV}")


if __name__ == "__main__":
    main()

