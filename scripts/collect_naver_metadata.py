#!/usr/bin/env python3
"""네이버 블로그/장소 검색으로 POI 메타데이터 수집 (1000개 샘플)"""

import csv
import json
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from tqdm import tqdm

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

CSV_PATH = ROOT / "data" / "pois_processed.csv"
OUTPUT_PATH = ROOT / "data" / "naver" / "naver_metadata.json"
PROGRESS_PATH = ROOT / "data" / "naver" / "naver_metadata_progress.json"

# ── API 설정 ───────────────────────────────────────────────────────────────────
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID") or os.getenv("NAVER_API_KEY", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_BLOG_URL = "https://openapi.naver.com/v1/search/blog.json"

NAVER_HEADERS = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

SAMPLE_SIZE = 1000
BLOG_DISPLAY = 5      # 장소당 블로그 결과 수
BATCH_SIZE = 15       # Claude 1회 호출당 POI 수
MAX_WORKERS = 8       # 병렬 HTTP 스레드 수 (Naver ~10 req/s 한도 감안)
NAVER_DELAY = 0.08    # 스레드당 요청 간격(초) — 8 workers × 12 req/s = safe
MAX_RETRIES = 3

# 스레드 안전 rate limiter: 초당 최대 10 req
_rate_lock = threading.Lock()
_last_request_times: list[float] = []
RATE_LIMIT_RPS = 10


def _rate_limited_get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """초당 요청 수를 RATE_LIMIT_RPS 이하로 제한"""
    with _rate_lock:
        now = time.monotonic()
        # 1초 윈도우 밖 요청 제거
        while _last_request_times and now - _last_request_times[0] > 1.0:
            _last_request_times.pop(0)
        if len(_last_request_times) >= RATE_LIMIT_RPS:
            wait = 1.0 - (now - _last_request_times[0])
            if wait > 0:
                time.sleep(wait)
        _last_request_times.append(time.monotonic())
    return client.get(url, **kwargs)


anthropic = Anthropic()

TYPE_LABEL = {
    "12": "관광지", "14": "문화시설", "15": "축제/행사",
    "25": "여행코스", "28": "레저스포츠", "32": "숙박",
    "38": "쇼핑", "39": "음식점",
}

EXTRACT_PROMPT = """\
다음은 한국 장소 {count}곳의 네이버 블로그 검색 결과입니다.
각 장소에 대해 아래 5가지 항목만 추출하세요.
블로그 내용에 명확한 근거가 없으면 반드시 null로 표시하세요. 추측 금지.

{places_block}

---
각 장소에 대해 아래 JSON 스키마로 결과를 반환하세요:
{{
  "contentid": "장소ID",
  "waiting": true/false/null,          // 웨이팅·줄서기 언급 여부
  "crowd_level": "low"/"medium"/"high"/null,  // 혼잡도 (한산/보통/복잡)
  "reservation_required": true/false/null,    // 예약 필수 여부
  "parking": true/false/null,                 // 주차 가능 여부
  "price_level": "cheap"/"normal"/"expensive"/null  // 가격대 (저렴/보통/비쌈)
}}

모든 장소를 포함하는 JSON 배열만 출력하세요. 다른 텍스트 없이."""


def load_csv_sample(size: int) -> list[dict]:
    """CSV에서 샘플 추출 (음식점·관광지 비중 높임)"""
    buckets: dict[str, list[dict]] = {}
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tid = row["contenttypeid"]
            buckets.setdefault(tid, []).append(row)

    weights = {
        "39": 0.30, "12": 0.25, "38": 0.15, "28": 0.10,
        "32": 0.08, "14": 0.07, "15": 0.03, "25": 0.02,
    }

    sample: list[dict] = []
    for tid, w in weights.items():
        pool = buckets.get(tid, [])
        n = min(int(size * w), len(pool))
        sample.extend(random.sample(pool, n))

    random.shuffle(sample)
    return sample[:size]


def fetch_blog(client: httpx.Client, poi: dict) -> tuple[dict, list[dict]]:
    """단일 POI의 블로그 결과 수집 (스레드풀에서 실행)"""
    # CSV는 addr1 없이 sido/sigungu로 분리 저장됨
    region = " ".join(filter(None, [poi.get("sido", ""), poi.get("sigungu", "")]))
    query = f"{poi['title']} {region}".strip()

    for attempt in range(MAX_RETRIES):
        try:
            resp = _rate_limited_get(
                client,
                NAVER_BLOG_URL,
                headers=NAVER_HEADERS,
                params={"query": query, "display": BLOG_DISPLAY, "sort": "sim"},
                timeout=10,
            )
            if resp.status_code == 401:
                print("\n[ERROR] 네이버 API 인증 실패: Client ID/Secret을 확인하세요.")
                sys.exit(1)
            if resp.status_code == 200:
                return poi, resp.json().get("items", [])
        except httpx.RequestError:
            pass
        time.sleep(0.5 * (attempt + 1))
    return poi, []


def build_place_block(poi: dict, blog_items: list[dict]) -> str:
    import re

    def strip_tags(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "")

    name = poi["title"]
    region = " ".join(filter(None, [poi.get("sido", ""), poi.get("sigungu", "")]))
    type_label = TYPE_LABEL.get(poi.get("contenttypeid", ""), "기타")

    lines = [f"[{poi['contentid']}] {name} ({type_label}) — {region}"]
    if blog_items:
        for i, item in enumerate(blog_items[:BLOG_DISPLAY], 1):
            title = strip_tags(item.get("title", ""))
            desc = strip_tags(item.get("description", ""))
            lines.append(f"  블로그{i}: {title} | {desc[:200]}")
    else:
        lines.append("  (검색 결과 없음)")
    return "\n".join(lines)


def extract_metadata_batch(batch: list[tuple[dict, list[dict]]]) -> list[dict]:
    places_block = "\n\n".join(
        build_place_block(poi, items) for poi, items in batch
    )
    prompt = EXTRACT_PROMPT.format(count=len(batch), places_block=places_block)

    for attempt in range(MAX_RETRIES):
        try:
            resp = anthropic.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as e:
            print(f"\n[WARN] Claude 추출 실패 (시도 {attempt+1}): {e}")
            time.sleep(2)
    return [{"contentid": poi["contentid"]} for poi, _ in batch]


def load_progress() -> dict[str, dict]:
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            return {r["contentid"]: r for r in json.load(f)}
    return {}


def save_progress(results: dict[str, dict]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(results.values()), f, ensure_ascii=False, indent=2)


def merge_meta(meta: dict, source: dict) -> dict:
    meta.update({
        "title": source["title"],
        "sido": source.get("sido", ""),
        "sigungu": source.get("sigungu", ""),
        "addr2": source.get("addr2", ""),
        "contenttypeid": source["contenttypeid"],
        "type_label": TYPE_LABEL.get(source["contenttypeid"], "기타"),
        "mapx": source.get("mapx"),
        "mapy": source.get("mapy"),
    })
    return meta


def main() -> None:
    if not NAVER_CLIENT_ID:
        print("[ERROR] NAVER_API_KEY 또는 NAVER_CLIENT_ID가 설정되지 않았습니다.")
        sys.exit(1)

    print(f"CSV에서 {SAMPLE_SIZE}개 샘플 추출 중...")
    pois = load_csv_sample(SAMPLE_SIZE)
    print(f"샘플 {len(pois)}개 추출 완료")

    done = load_progress()
    remaining = [p for p in pois if p["contentid"] not in done]
    print(f"남은 작업: {len(remaining)}개 (완료: {len(done)}개)")

    t0 = time.monotonic()

    # ── 1단계: 병렬 Naver 블로그 검색 ────────────────────────────────────────
    print(f"\n[1/2] 네이버 블로그 검색 (workers={MAX_WORKERS}) ...")
    blog_results: list[tuple[dict, list[dict]]] = []

    with httpx.Client() as http:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_blog, http, poi): poi for poi in remaining}
            with tqdm(total=len(remaining), desc="블로그 검색") as pbar:
                for fut in as_completed(futures):
                    blog_results.append(fut.result())
                    pbar.update(1)

    http_elapsed = time.monotonic() - t0
    print(f"  → HTTP 완료: {http_elapsed:.1f}s ({len(blog_results)}건)")

    # ── 2단계: Claude 배치 메타데이터 추출 ───────────────────────────────────
    print(f"\n[2/2] Claude 메타데이터 추출 (batch={BATCH_SIZE}) ...")
    t1 = time.monotonic()

    for i in tqdm(range(0, len(blog_results), BATCH_SIZE), desc="Claude 배치"):
        batch = blog_results[i : i + BATCH_SIZE]
        extracted = extract_metadata_batch(batch)
        poi_map = {p["contentid"]: p for p, _ in batch}
        for meta in extracted:
            cid = meta.get("contentid")
            if cid and cid in poi_map:
                done[cid] = merge_meta(meta, poi_map[cid])
        save_progress(done)

    claude_elapsed = time.monotonic() - t1
    total_elapsed = time.monotonic() - t0

    # ── 최종 저장 ─────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    final = list(done.values())
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    # ── 요약 통계 ─────────────────────────────────────────────────────────────
    n = max(len(final), 1)
    fields = ["waiting", "crowd_level", "reservation_required", "parking", "price_level"]

    waiting_true   = sum(1 for r in final if r.get("waiting") is True)
    high_crowd     = sum(1 for r in final if r.get("crowd_level") == "high")
    reservation    = sum(1 for r in final if r.get("reservation_required") is True)
    parking_ok     = sum(1 for r in final if r.get("parking") is True)
    expensive      = sum(1 for r in final if r.get("price_level") == "expensive")
    all_null_ratio = sum(
        1 for r in final if all(r.get(f) is None for f in fields)
    ) / n

    print(f"\n── 완료 ─────────────────────────────────────────────────────────")
    print(f"  총 {len(final)}개 → {OUTPUT_PATH}")
    print(f"  HTTP: {http_elapsed:.1f}s  |  Claude: {claude_elapsed:.1f}s  |  합계: {total_elapsed:.1f}s")
    print(f"  웨이팅 있음:   {waiting_true:4d} ({waiting_true/n*100:.1f}%)")
    print(f"  혼잡도 높음:   {high_crowd:4d} ({high_crowd/n*100:.1f}%)")
    print(f"  예약 필수:     {reservation:4d} ({reservation/n*100:.1f}%)")
    print(f"  주차 가능:     {parking_ok:4d} ({parking_ok/n*100:.1f}%)")
    print(f"  가격대 비쌈:   {expensive:4d} ({expensive/n*100:.1f}%)")
    print(f"  전체 null(5항목):  {all_null_ratio*100:.1f}%  ← 데이터 희소성 지표")


if __name__ == "__main__":
    random.seed(42)
    main()
