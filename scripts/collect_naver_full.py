#!/usr/bin/env python3
"""네이버 블로그 검색 — 전체 POI 메타데이터 수집 (재개 가능, 일일 한도 관리)

전략:
  - CSV의 50,745개 전체를 수집 (샘플링 없음)
  - contentid 기준 progress 추적 → 중단 후 재개 가능
  - 일일 API 호출 한도 관리: DAILY_CALL_LIMIT(기본 23,000) 도달 시 자동 종료
    → Naver 무료 플랜 25,000 calls/day에서 2,000 안전 마진
  - 우선순위: 관광지(12) → 음식점(39) → 문화시설(14) → 레저(28) → 나머지
  - 수집 완료 시 naver_metadata.json에 전체 결과 저장

실행:
  python3 scripts/collect_naver_full.py              # 오늘 남은 한도만큼 수집
  python3 scripts/collect_naver_full.py --limit 5000  # 오늘 최대 5000 POI만
  python3 scripts/collect_naver_full.py --dry-run     # 수집 안 하고 현황만 출력

진행 파일:
  data/naver/naver_progress.json  ← contentid → record (기존 호환)
  data/naver/daily_quota.json     ← 날짜별 API 호출 카운터
"""

import argparse
import csv
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

# ── 파일 경로 ──────────────────────────────────────────────────────────────────
CSV_PATH      = ROOT / "data" / "pois_processed.csv"
OUTPUT_PATH   = ROOT / "data" / "naver" / "naver_metadata.json"
PROGRESS_PATH = ROOT / "data" / "naver" / "naver_progress.json"
QUOTA_PATH    = ROOT / "data" / "naver" / "daily_quota.json"

# ── Naver API 설정 ─────────────────────────────────────────────────────────────
NAVER_CLIENT_ID     = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_BLOG_URL      = "https://openapi.naver.com/v1/search/blog.json"
NAVER_HEADERS       = {
    "X-Naver-Client-Id":     NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

# ── 수집 설정 ──────────────────────────────────────────────────────────────────
BLOG_DISPLAY    = 10         # 쿼리당 블로그 수 (최대 10)
MAX_WORKERS     = 8          # 병렬 스레드 수
MAX_RETRIES     = 3          # API 재시도
RATE_LIMIT_RPS  = 9          # 초당 최대 요청 수
DAILY_CALL_LIMIT = 23_000    # 일일 API 호출 한도 (25000에서 2000 마진)
CALLS_PER_POI   = 2          # POI당 API 호출 수 (dual query)
SAVE_INTERVAL   = 50         # 중간 저장 주기

# ── 우선순위 (검증 중요도 순) ──────────────────────────────────────────────────
TYPE_PRIORITY = {
    "12": 1,  # 관광지 — 운영시간 검증에 핵심
    "39": 2,  # 음식점 — 웨이팅/예약 중요
    "14": 3,  # 문화시설
    "28": 4,  # 레저스포츠
    "38": 5,  # 쇼핑
    "32": 6,  # 숙박 (depot, 검증 덜 중요)
    "15": 7,  # 축제/행사
    "25": 8,  # 여행코스
}

TYPE_LABEL = {
    "12": "관광지", "14": "문화시설", "15": "축제/행사",
    "25": "여행코스", "28": "레저스포츠", "32": "숙박",
    "38": "쇼핑", "39": "음식점",
}

TYPE_QUERY_SUFFIX = {
    "39": "맛집 후기", "12": "여행 후기", "32": "숙박 후기",
    "38": "쇼핑 후기", "28": "체험 후기", "14": "관람 후기",
    "15": "축제 후기", "25": "여행코스 후기",
}

# ── Rate limiter ───────────────────────────────────────────────────────────────
_rate_lock = threading.Lock()
_req_times: list = []

def _rate_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    with _rate_lock:
        now = time.monotonic()
        while _req_times and now - _req_times[0] > 1.0:
            _req_times.pop(0)
        if len(_req_times) >= RATE_LIMIT_RPS:
            wait = 1.0 - (now - _req_times[0])
            if wait > 0:
                time.sleep(wait)
        _req_times.append(time.monotonic())
    return client.get(url, **kwargs)


# ── 일일 쿼터 관리 ─────────────────────────────────────────────────────────────
_quota_lock = threading.Lock()
_daily_calls = 0

def load_quota() -> int:
    """오늘 날짜 기준 남은 API 호출 수 반환."""
    global _daily_calls
    today = str(date.today())
    if QUOTA_PATH.exists():
        with open(QUOTA_PATH) as f:
            q = json.load(f)
        if q.get("date") == today:
            _daily_calls = q.get("calls", 0)
            return DAILY_CALL_LIMIT - _daily_calls
    _daily_calls = 0
    return DAILY_CALL_LIMIT

def _save_quota():
    with open(QUOTA_PATH, "w") as f:
        json.dump({"date": str(date.today()), "calls": _daily_calls}, f)

def _increment_quota(n: int = 1) -> bool:
    """호출 카운트 증가. 한도 초과 시 False 반환."""
    global _daily_calls
    with _quota_lock:
        _daily_calls += n
        if _daily_calls % 100 == 0:
            _save_quota()
        return _daily_calls <= DAILY_CALL_LIMIT


# ── 키워드 사전 ────────────────────────────────────────────────────────────────
def _strip(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")

RULES = {
    "waiting": (
        ["웨이팅", "대기줄", "줄서", "오픈런", "대기 시간", "기다려야", "대기번호",
         "웨이팅 있", "줄이 길", "번호표", "입장 대기", "웨이팅 걸", "대기 엄청",
         "오래 기다", "줄을 서야", "웨이팅 필수", "줄서서먹", "대기가 있", "줄이 있",
         "기다림이", "만석", "웨이팅 후", "대기표", "웨이팅이", "대기해야",
         "한참 기다", "30분 대기", "1시간 대기", "2시간 대기", "줄이 어마",
         "줄이 길게", "웨이팅 각오", "줄 서야", "항상 줄"],
        ["웨이팅 없", "대기 없", "줄 없", "바로 입장", "바로 들어", "웨이팅 안",
         "줄 안 서", "대기 없이", "바로 앉", "바로 이용", "기다림 없",
         "웨이팅 없이", "줄 없이", "바로 자리", "빈자리"],
    ),
    "crowd_high": (
        ["혼잡", "붐비", "북적", "인산인해", "사람 많", "항상 줄", "늘 대기",
         "주말 대기", "핫플", "줄이 길", "항상 붐", "사람이 많", "엄청 많",
         "발 디딜", "가득", "줄이 어마", "웨이팅 있", "줄서서", "대기가 어마",
         "인기 많", "항상 만원", "자리 없", "대기자 많"],
        [],
    ),
    "crowd_low": (
        ["한산", "여유롭", "조용", "한적", "사람 적", "여유 있", "쾌적",
         "한가", "사람이 없", "인적 드", "비교적 여유", "조용한 편",
         "사람이 적", "덜 붐비", "붐비지 않", "한산한 편", "여유있게",
         "한적한 편", "여유롭게", "조용히", "한산하게"],
        [],
    ),
    "reservation_required": (
        ["예약 필수", "예약제", "사전예약", "예약해야", "예약 없이는", "예약 안 하면",
         "예약하고", "예약 후 방문", "예약 후에", "네이버 예약", "카카오 예약",
         "전화 예약", "예약 없으면", "예약을 해야", "예약제 운영", "예약 필요",
         "예약하지 않으면", "예약이 필수", "미리 예약", "예약 후 이용",
         "예약제로 운영", "사전 예약", "온라인 예약", "예약 후에만"],
        ["예약 없이", "예약 안 해도", "당일 방문 가능", "예약 불필요",
         "예약 없어도", "예약 안해도", "워크인", "예약 없이도"],
    ),
    "parking_ok": (
        ["주차장", "주차 가능", "주차 있", "주차공간", "무료주차", "유료주차",
         "주차 편리", "주차 넉넉", "주차장 있", "주차 편", "주차 무료",
         "주차장이 있", "넓은 주차", "주차 여유", "주차장 완비", "공용 주차",
         "인근 주차", "주차 OK", "주차가 편", "주차가 넉넉", "주차 쉬움",
         "주차 공간 넉넉", "주차 문제 없", "주차 편하"],
        ["주차 불가", "주차 없", "주차 어렵", "주차난", "주차 힘",
         "주차 못", "주차가 없", "주차 공간 없", "주차하기 어",
         "주차 불편", "주차 걱정"],
    ),
    "price_low": (
        ["가성비", "저렴", "착한 가격", "싸다", "싼 편", "합리적", "저가",
         "가격이 착", "저렴한 편", "가성비 좋", "가격 대비", "저렴하게",
         "가격이 저", "착하다", "가격이 합리", "저렴한 가격", "알뜰",
         "가격대가 낮", "부담 없는 가격", "가격이 괜찮", "가격이 저렴",
         "싸게", "저렴하게 즐길", "착한 편", "가성비 맛집", "저렴이",
         "백반", "분식", "국밥", "자판기", "무료 입장", "입장 무료"],
        [],
    ),
    "price_high": (
        ["비싸다", "비싼 편", "가격이 높", "고가", "프리미엄", "값이 비",
         "좀 비싸", "가격이 비", "비용이 높", "부담되는 가격", "가격 부담",
         "비싼 가격", "가격대가 높", "파인다이닝", "고급 레스토랑",
         "가격이 센", "금액이 높", "럭셔리", "가격이 세다", "꽤 비싸",
         "가격이 좀", "비싸지만", "비싼 편이지만", "가격 있는",
         "오마카세", "코스요리", "파인", "하이엔드", "스파", "루프탑",
         "호텔 레스토랑", "미슐랭", "외제차", "레드카펫"],
        [],
    ),
    "sentiment_neg": (
        ["별로", "실망", "아쉽", "최악", "불친절", "위생", "바가지",
         "다시는", "후회", "비추", "노추천", "하지마", "낚였", "낭패",
         "실패", "별점 1", "1점", "환불", "불만", "불쾌"],
        [],
    ),
}


def _count_hits(text: str, patterns: list) -> int:
    return sum(1 for p in patterns if p in text)


_PRICE_RE = re.compile(
    r"(?:1인당|인당|1인|가격|금액|요금|입장료|이용료|비용|티켓)[\s:]*"
    r"([0-9,]+)\s*원"
    r"|([0-9]+)만\s*원"
    r"|([0-9]+)천\s*원"
    r"|([0-9]+),([0-9]{3})\s*원"
)

_TYPE_THRESHOLDS = {
    "39": (12000, 30000), "32": (60000, 180000), "12": (3000, 15000),
    "38": (10000, 50000), "28": (15000, 60000),  "14": (2000, 10000),
    "15": (5000, 20000),
}

def _parse_price(text: str, type_id: str):
    low_thr, high_thr = _TYPE_THRESHOLDS.get(type_id, (15000, 50000))
    prices = []
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1) or m.group(4)
        if raw:
            prices.append(int(raw.replace(",", "")))
        elif m.group(2):
            prices.append(int(m.group(2)) * 10000)
        elif m.group(3):
            prices.append(int(m.group(3)) * 1000)
        elif m.group(4) and m.group(5):
            prices.append(int(m.group(4)) * 1000 + int(m.group(5)))
    if not prices:
        return None
    avg = sum(prices) / len(prices)
    if avg <= low_thr:
        return "low"
    if avg >= high_thr:
        return "high"
    return "medium"


def extract_fields(texts: list, type_id: str = "") -> dict:
    combined = " ".join(texts)

    def decide(pos_key: str):
        pos_pats, neg_pats = RULES[pos_key]
        h_pos = _count_hits(combined, pos_pats)
        h_neg = _count_hits(combined, neg_pats)
        if h_pos == 0 and h_neg == 0:
            return None
        return h_pos > h_neg

    waiting              = decide("waiting")
    reservation_required = decide("reservation_required")
    parking              = decide("parking_ok")

    h_high = _count_hits(combined, RULES["crowd_high"][0])
    h_low  = _count_hits(combined, RULES["crowd_low"][0])
    total  = h_high + h_low
    if total == 0:
        crowd_level = None
    elif h_high >= h_low * 2:
        crowd_level = "high"
    elif h_low >= h_high * 2:
        crowd_level = "low"
    else:
        crowd_level = "medium"

    h_low_p  = _count_hits(combined, RULES["price_low"][0])
    h_high_p = _count_hits(combined, RULES["price_high"][0])
    if h_low_p == 0 and h_high_p == 0:
        price_level = _parse_price(combined, type_id)
    elif h_high_p > h_low_p:
        price_level = "high"
    elif h_low_p > h_high_p:
        price_level = "low"
    else:
        price_level = "medium"

    h_neg = _count_hits(combined, RULES["sentiment_neg"][0])
    sentiment = "negative" if h_neg >= 2 else None

    return {
        "waiting":              waiting,
        "crowd_level":          crowd_level,
        "reservation_required": reservation_required,
        "parking":              parking,
        "price_level":          price_level,
        "sentiment":            sentiment,
    }


_FIELD_TEXT = {
    "waiting":              {True: "웨이팅 있음", False: "웨이팅 없음"},
    "crowd_level":          {"high": "혼잡도 높음", "medium": "혼잡도 보통", "low": "한산함"},
    "reservation_required": {True: "예약 필수", False: "예약 불필요"},
    "parking":              {True: "주차 가능", False: "주차 불가"},
    "price_level":          {"high": "가격대 높음", "medium": "가격대 보통", "low": "가격대 낮음"},
    "sentiment":            {"negative": "부정 리뷰 있음"},
}

def build_summary_text(record: dict) -> str:
    parts = [
        f"{record.get('sido','')} {record.get('sigungu','')}의 "
        f"{record.get('type_label','장소')} [{record['title']}]."
    ]
    for field, val_map in _FIELD_TEXT.items():
        val = record.get(field)
        if val is not None and val in val_map:
            parts.append(val_map[val] + ".")
    return " ".join(parts)


# ── Naver API ──────────────────────────────────────────────────────────────────
def _fetch_blog_texts(client: httpx.Client, query: str) -> list:
    for attempt in range(MAX_RETRIES):
        try:
            resp = _rate_get(
                client, NAVER_BLOG_URL,
                headers=NAVER_HEADERS,
                params={"query": query, "display": BLOG_DISPLAY, "sort": "sim"},
                timeout=10,
            )
            if resp.status_code == 401:
                print("\n[ERROR] 네이버 인증 실패 — NAVER_CLIENT_ID / SECRET 확인")
                sys.exit(1)
            if resp.status_code == 429:
                print("\n[WARN] 네이버 API 일일 한도 초과 (429)")
                return []
            if resp.status_code == 200:
                return [
                    _strip(it.get("title", "")) + " " + _strip(it.get("description", ""))
                    for it in resp.json().get("items", [])
                ]
        except httpx.RequestError:
            pass
        time.sleep(0.4 * (attempt + 1))
    return []


def fetch_and_extract(client: httpx.Client, poi: dict) -> dict:
    title   = poi["title"]
    sigungu = poi.get("sigungu", "")
    type_id = poi.get("contenttypeid", "")
    suffix  = TYPE_QUERY_SUFFIX.get(type_id, "후기")

    # 쿼터 확인 — 한도 초과 시 빈 결과 반환
    if not _increment_quota(CALLS_PER_POI):
        return {
            "contentid": poi["contentid"], "title": title,
            "_quota_exceeded": True,
        }

    texts1 = _fetch_blog_texts(client, f"{title} {sigungu} {suffix}".strip())
    texts2 = _fetch_blog_texts(client, title)

    seen: set = set()
    all_texts: list = []
    for t in texts1 + texts2:
        key = t[:60]
        if key not in seen:
            seen.add(key)
            all_texts.append(t)

    fields = extract_fields(all_texts, type_id)
    fields.update({
        "contentid":     poi["contentid"],
        "title":         title,
        "sido":          poi.get("sido", ""),
        "sigungu":       sigungu,
        "addr2":         poi.get("addr2", ""),
        "contenttypeid": type_id,
        "type_label":    TYPE_LABEL.get(type_id, "기타"),
        "mapx":          poi.get("mapx"),
        "mapy":          poi.get("mapy"),
        "blog_count":    len(all_texts),
    })
    fields["summary_text"] = build_summary_text(fields)
    return fields


# ── CSV 전체 로드 (우선순위 정렬) ──────────────────────────────────────────────
def load_all_pois() -> list:
    rows = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    rows.sort(key=lambda r: TYPE_PRIORITY.get(r.get("contenttypeid", ""), 99))
    return rows


# ── Progress 관리 ──────────────────────────────────────────────────────────────
def load_progress() -> dict:
    """contentid → record 딕셔너리 반환 (progress 파일이 list 형식도 처리)."""
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return {r["contentid"]: r for r in raw}
        if isinstance(raw, dict):
            return raw
    return {}

def save_progress(results: dict) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(results.values()), f, ensure_ascii=False, indent=2)

def save_output(results: dict) -> None:
    final = [r for r in results.values() if not r.get("_quota_exceeded")]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    return final


# ── 현황 출력 ──────────────────────────────────────────────────────────────────
def print_stats(final: list) -> None:
    n = max(len(final), 1)
    fields = ["waiting", "crowd_level", "reservation_required", "parking", "price_level", "sentiment"]

    def cnt(cond):
        return sum(1 for r in final if cond(r))

    print(f"\n── 수집 현황 ({len(final)}개 / 50,745개) ──────────────────")
    print(f"  수집률: {len(final)/50745*100:.1f}%")
    print(f"  블로그 평균: {sum(r.get('blog_count',0) for r in final)/n:.1f}개/POI")
    print(f"  [웨이팅]    True:{cnt(lambda r:r.get('waiting') is True):5d}  False:{cnt(lambda r:r.get('waiting') is False):5d}  null:{cnt(lambda r:r.get('waiting') is None):5d}")
    for v in ("high", "medium", "low"):
        c = cnt(lambda r, v=v: r.get("crowd_level") == v)
        print(f"  [혼잡도-{v:6s}] {c:5d} ({c/n*100:.1f}%)")
    print(f"  [예약필수]  True:{cnt(lambda r:r.get('reservation_required') is True):5d}  null:{cnt(lambda r:r.get('reservation_required') is None):5d}")
    print(f"  [주차가능]  True:{cnt(lambda r:r.get('parking') is True):5d}  null:{cnt(lambda r:r.get('parking') is None):5d}")
    for v in ("high", "medium", "low"):
        c = cnt(lambda r, v=v: r.get("price_level") == v)
        print(f"  [가격-{v:6s}]  {c:5d} ({c/n*100:.1f}%)")
    neg = cnt(lambda r: r.get("sentiment") == "negative")
    print(f"  [부정리뷰]         {neg:5d} ({neg/n*100:.1f}%)")
    anull = cnt(lambda r: all(r.get(k) is None for k in fields))
    print(f"  전체 null(6항목):  {anull:5d} ({anull/n*100:.1f}%)")

    # 타입별 수집 현황
    from collections import Counter
    type_cnt = Counter(r.get("contenttypeid", "?") for r in final)
    print("\n  [타입별 수집]")
    for tid, label in TYPE_LABEL.items():
        print(f"    {label}({tid}): {type_cnt.get(tid, 0):5d}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="네이버 전체 POI 메타데이터 수집")
    parser.add_argument("--limit", type=int, default=None,
                        help="오늘 수집할 최대 POI 수 (기본: 일일 API 한도 기준 자동)")
    parser.add_argument("--dry-run", action="store_true",
                        help="수집 없이 현황만 출력")
    args = parser.parse_args()

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("[ERROR] NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 없음")
        sys.exit(1)

    # 현황 로드
    done      = load_progress()
    all_pois  = load_all_pois()
    remaining = [p for p in all_pois if p["contentid"] not in done]

    remaining_quota = load_quota()
    max_poi_today   = remaining_quota // CALLS_PER_POI
    if args.limit:
        max_poi_today = min(max_poi_today, args.limit)

    print(f"전체 POI: {len(all_pois):,}개")
    print(f"수집 완료: {len(done):,}개 ({len(done)/len(all_pois)*100:.1f}%)")
    print(f"미수집: {len(remaining):,}개")
    print(f"오늘 남은 API 호출: {remaining_quota:,} (≈ {max_poi_today:,} POI)")
    print(f"오늘 수집 대상: {min(max_poi_today, len(remaining)):,}개")

    if args.dry_run:
        final = [r for r in done.values() if not r.get("_quota_exceeded")]
        print_stats(final)
        return

    if max_poi_today <= 0:
        print("[INFO] 오늘 일일 API 한도 소진. 내일 다시 실행하세요.")
        return

    target = remaining[:max_poi_today]
    if not target:
        print("[INFO] 수집할 POI 없음. 완료 상태입니다.")
        final = save_output(done)
        print_stats(final)
        return

    t0 = time.monotonic()
    quota_exceeded = False
    batch_buf = []

    with httpx.Client() as http:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_and_extract, http, poi): poi for poi in target}

            with tqdm(total=len(target), desc="수집 중") as pbar:
                for fut in as_completed(futures):
                    result = fut.result()

                    if result.get("_quota_exceeded"):
                        quota_exceeded = True
                        pbar.update(1)
                        continue

                    done[result["contentid"]] = result
                    batch_buf.append(result)
                    pbar.update(1)

                    if len(batch_buf) >= SAVE_INTERVAL:
                        save_progress(done)
                        batch_buf.clear()

            if batch_buf:
                save_progress(done)

    _save_quota()
    elapsed = time.monotonic() - t0
    final = save_output(done)

    new_count = len([r for r in done.values() if not r.get("_quota_exceeded")]) - (len(all_pois) - len(remaining))
    print(f"\n── 오늘 수집 완료 ({elapsed:.0f}s) ──────────────────────────")
    print(f"  이번 실행 수집: {new_count}개")
    print(f"  누적 수집: {len(final):,}개 / {len(all_pois):,}개")
    print(f"  남은 오늘 API 호출: {DAILY_CALL_LIMIT - _daily_calls:,}")
    if quota_exceeded:
        print("  ⚠ 일일 한도에 도달했습니다. 내일 다시 실행하세요.")

    print_stats(final)


if __name__ == "__main__":
    main()
