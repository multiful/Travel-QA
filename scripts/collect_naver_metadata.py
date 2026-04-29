#!/usr/bin/env python3
"""네이버 블로그/장소 검색으로 POI 메타데이터 수집 (1000개 샘플)"""

import csv
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from tqdm import tqdm

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

CSV_PATH = ROOT / "pois_processed.csv"
OUTPUT_PATH = ROOT / "data" / "naver_metadata.json"
PROGRESS_PATH = ROOT / "data" / "naver_metadata_progress.json"

# ── API 설정 ───────────────────────────────────────────────────────────────────
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID") or os.getenv("NAVER_API_KEY", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
NAVER_BLOG_URL = "https://openapi.naver.com/v1/search/blog.json"
NAVER_LOCAL_URL = "https://openapi.naver.com/v1/search/local.json"

NAVER_HEADERS = {
    "X-Naver-Client-Id": NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
}

SAMPLE_SIZE = 1000
BLOG_DISPLAY = 5      # 장소당 블로그 결과 수
BATCH_SIZE = 15       # Claude 1회 호출당 POI 수
NAVER_DELAY = 0.12    # Naver API 호출 간격(초)
MAX_RETRIES = 3

anthropic = Anthropic()

# contenttypeid 레이블
TYPE_LABEL = {
    "12": "관광지", "14": "문화시설", "15": "축제/행사",
    "25": "여행코스", "28": "레저스포츠", "32": "숙박",
    "38": "쇼핑", "39": "음식점",
}

EXTRACT_PROMPT = """\
다음은 한국 장소 {count}곳의 네이버 블로그/장소 검색 결과입니다.
각 장소에 대해 아래 JSON 형식으로 메타데이터를 추출하세요.
정보가 검색 결과에 없으면 null로 표시하세요.

{places_block}

---
각 장소에 대해 아래 JSON 스키마로 결과를 반환하세요:
{{
  "contentid": "장소ID",
  "waiting": true/false/null,
  "waiting_time_min": 숫자/null,
  "crowd_level": "low"/"medium"/"high"/null,
  "quiet": true/false/null,
  "food_quantity": "small"/"normal"/"large"/null,
  "price_level": "cheap"/"normal"/"expensive"/null,
  "parking": true/false/null,
  "reservation_required": true/false/null,
  "view_scenery": true/false/null,
  "pet_friendly": true/false/null,
  "kids_friendly": true/false/null,
  "solo_friendly": true/false/null,
  "date_spot": true/false/null,
  "photo_spot": true/false/null,
  "sentiment": "positive"/"neutral"/"negative"/null,
  "keywords": ["키워드1", "키워드2", ...]
}}

모든 장소를 포함하는 JSON 배열만 출력하세요. 다른 텍스트 없이."""


def load_csv_sample(size: int) -> list[dict]:
    """CSV에서 샘플 추출 (음식점·관광지 비중 높임)"""
    buckets: dict[str, list[dict]] = {}
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tid = row["contenttypeid"]
            buckets.setdefault(tid, []).append(row)

    # 타입별 목표 비율 (합 = 1.0)
    weights = {
        "39": 0.30,   # 음식점
        "12": 0.25,   # 관광지
        "38": 0.15,   # 쇼핑
        "28": 0.10,   # 레저스포츠
        "32": 0.08,   # 숙박
        "14": 0.07,   # 문화시설
        "15": 0.03,   # 축제
        "25": 0.02,   # 여행코스
    }

    sample: list[dict] = []
    for tid, w in weights.items():
        pool = buckets.get(tid, [])
        n = min(int(size * w), len(pool))
        sample.extend(random.sample(pool, n))

    random.shuffle(sample)
    return sample[:size]


def search_naver_blog(client: httpx.Client, query: str) -> list[dict]:
    """네이버 블로그 검색"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(
                NAVER_BLOG_URL,
                headers=NAVER_HEADERS,
                params={"query": query, "display": BLOG_DISPLAY, "sort": "sim"},
                timeout=10,
            )
            if resp.status_code == 401:
                print("\n[ERROR] 네이버 API 인증 실패: Client ID/Secret을 확인하세요.")
                sys.exit(1)
            if resp.status_code == 200:
                return resp.json().get("items", [])
        except httpx.RequestError:
            pass
        time.sleep(0.5 * (attempt + 1))
    return []


def build_place_block(poi: dict, blog_items: list[dict]) -> str:
    """Claude에 보낼 장소 텍스트 블록 생성"""
    import re

    def strip_tags(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "")

    name = poi["title"]
    addr = poi.get("addr1", "")
    type_label = TYPE_LABEL.get(poi.get("contenttypeid", ""), "기타")

    lines = [f"[{poi['contentid']}] {name} ({type_label}) — {addr}"]
    if blog_items:
        for i, item in enumerate(blog_items[:BLOG_DISPLAY], 1):
            title = strip_tags(item.get("title", ""))
            desc = strip_tags(item.get("description", ""))
            lines.append(f"  블로그{i}: {title} | {desc[:200]}")
    else:
        lines.append("  (검색 결과 없음)")
    return "\n".join(lines)


def extract_metadata_batch(batch: list[tuple[dict, list[dict]]]) -> list[dict]:
    """Claude로 배치 메타데이터 추출"""
    places_block = "\n\n".join(
        build_place_block(poi, items) for poi, items in batch
    )
    prompt = EXTRACT_PROMPT.format(count=len(batch), places_block=places_block)

    for attempt in range(MAX_RETRIES):
        try:
            resp = anthropic.messages.create(
                model="claude-haiku-4-5-20251001",  # 비용 절감
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            # JSON 배열 파싱
            start = raw.find("[")
            end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as e:
            print(f"\n[WARN] Claude 추출 실패 (시도 {attempt+1}): {e}")
            time.sleep(2)
    # 실패 시 contentid만 포함한 null 레코드 반환
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


def main() -> None:
    if not NAVER_CLIENT_ID:
        print("[ERROR] NAVER_API_KEY 또는 NAVER_CLIENT_ID가 설정되지 않았습니다.")
        sys.exit(1)

    print(f"CSV에서 {SAMPLE_SIZE}개 샘플 추출 중...")
    pois = load_csv_sample(SAMPLE_SIZE)
    print(f"샘플 {len(pois)}개 추출 완료")

    # 이전 진행 상황 로드 (재시작 가능)
    done = load_progress()
    remaining = [p for p in pois if p["contentid"] not in done]
    print(f"남은 작업: {len(remaining)}개 (완료: {len(done)}개)")

    with httpx.Client() as http:
        pbar = tqdm(total=len(remaining), desc="메타데이터 수집")
        batch: list[tuple[dict, list[dict]]] = []

        for poi in remaining:
            query = f"{poi['title']} {poi.get('addr1', '').split()[0] if poi.get('addr1') else ''}"
            blog_items = search_naver_blog(http, query)
            time.sleep(NAVER_DELAY)
            batch.append((poi, blog_items))

            if len(batch) >= BATCH_SIZE:
                extracted = extract_metadata_batch(batch)
                # 원본 POI 필드와 병합
                poi_map = {p["contentid"]: p for p, _ in batch}
                for meta in extracted:
                    cid = meta.get("contentid")
                    if cid and cid in poi_map:
                        source = poi_map[cid]
                        meta.update({
                            "title": source["title"],
                            "addr1": source["addr1"],
                            "contenttypeid": source["contenttypeid"],
                            "type_label": TYPE_LABEL.get(source["contenttypeid"], "기타"),
                            "mapx": source.get("mapx"),
                            "mapy": source.get("mapy"),
                        })
                        done[cid] = meta
                save_progress(done)
                pbar.update(len(batch))
                batch = []

        # 나머지 처리
        if batch:
            extracted = extract_metadata_batch(batch)
            poi_map = {p["contentid"]: p for p, _ in batch}
            for meta in extracted:
                cid = meta.get("contentid")
                if cid and cid in poi_map:
                    source = poi_map[cid]
                    meta.update({
                        "title": source["title"],
                        "addr1": source["addr1"],
                        "contenttypeid": source["contenttypeid"],
                        "type_label": TYPE_LABEL.get(source["contenttypeid"], "기타"),
                        "mapx": source.get("mapx"),
                        "mapy": source.get("mapy"),
                    })
                    done[cid] = meta
            save_progress(done)
            pbar.update(len(batch))

        pbar.close()

    # 최종 저장
    final = list(done.values())
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(final)}개 → {OUTPUT_PATH}")

    # 간단한 통계
    waiting_count = sum(1 for r in final if r.get("waiting") is True)
    high_crowd = sum(1 for r in final if r.get("crowd_level") == "high")
    positive = sum(1 for r in final if r.get("sentiment") == "positive")
    print(f"  웨이팅 있음: {waiting_count}개")
    print(f"  혼잡도 높음: {high_crowd}개")
    print(f"  긍정 반응: {positive}개")


if __name__ == "__main__":
    random.seed(42)
    main()
