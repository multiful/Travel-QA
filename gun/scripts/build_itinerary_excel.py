"""추천 일정 → 매칭 → 시간 계산 → Excel 출력 파이프라인
============================================================
입력: gun/data/recommendations_input.xlsx
출력:
  - gun/data/itinerary_results_YYYYMMDD.xlsx   (메인 결과)
  - gun/data/match_failed.csv                  (매칭 실패 POI)
  - gun/data/kakao_route_cache.json            (이동시간 캐시 — 재실행 시 절약)

처리 흐름
---------
1. 입력 Excel 읽기 (Long format: 한 row = 한 장소)
2. 각 장소를 pois.csv와 매칭 (정확 → 부분 → 폴백 Kakao Local)
3. 매칭 결과로 카테고리/체류시간 자동 채움 (dwell_db 5단계 폴백)
4. 같은 plan_id+day 내 인접 장소 간 Kakao Mobility 이동시간 호출
5. 일정 단위 패널티 계산 (cluster_dispersion + travel_ratio + VRPTW)
6. 결과 Excel 출력 (입력 컬럼 + 자동 채움 컬럼)

사용:
    python3 gun/scripts/build_itinerary_excel.py
    python3 gun/scripts/build_itinerary_excel.py --no-kakao   # API 호출 없이 Haversine 폴백만
    python3 gun/scripts/build_itinerary_excel.py --input X.xlsx
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date as _date
from pathlib import Path
from typing import Any

import pandas as pd

# ── 프로젝트 루트 sys.path ─────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.data.dwell_db import get_recommended_dwell                # noqa: E402
from src.data.models import VRPTWDay, VRPTWPlace                   # noqa: E402
from src.scoring.cluster_dispersion import evaluate_cluster_dispersion  # noqa: E402
from src.scoring.travel_ratio import evaluate_travel_ratio          # noqa: E402
from src.validation.kakao_matrix import KakaoMobilityMatrix         # noqa: E402
from src.validation.vrptw_engine import HaversineMatrix             # noqa: E402

# ── 경로 ──────────────────────────────────────────────────────────────
GUN_DIR    = _PROJECT_ROOT / "gun"
DATA_DIR   = GUN_DIR / "data"
INPUT_XLSX  = DATA_DIR / "recommendations_input.xlsx"
POIS_CSV    = DATA_DIR / "pois_processed.csv"
CACHE_JSON  = DATA_DIR / "kakao_route_cache.json"
FAILED_CSV  = DATA_DIR / "match_failed.csv"


# ── 입력 컬럼 ─────────────────────────────────────────────────────────
INPUT_COLS = [
    "source", "plan_id", "시도", "시군구", "여행기간", "일자",
    "day", "방문순서", "여행지명", "카테고리힌트",
]

# ── 출력 컬럼 (입력 + 자동 채움) ──────────────────────────────────────
OUTPUT_COLS = INPUT_COLS + [
    # POI 매칭 결과
    "matched_title", "contentid", "contenttypeid", "lclsSystm1", "lclsSystm3",
    "mapx", "mapy", "매칭상태",
    # 시간 계산
    "체류시간_분", "체류출처", "다음장소_이동시간_분",
    # 일정 단위 (모든 row에 중복)
    "총_체류시간_분", "총_이동시간_분", "총_일정시간_분",
    # 패널티
    "risk_score", "travel_ratio", "cluster_penalty",
    "vrptw_warnings", "비고",
]

# ── 9시 출발 고정, 영업시간 검증 폴백 ────────────────────────────────
DEFAULT_START = "09:00"
DEFAULT_OPEN  = "09:00"
DEFAULT_CLOSE = "22:00"


# ────────────────────────────────────────────────────────────────────
# 1. POI 매칭 (정확 → 부분 → 폴백)
# ────────────────────────────────────────────────────────────────────
class POIMatcher:
    """pois_processed.csv 기반 이름 매칭 — 정확/부분 일치."""

    def __init__(self, pois_csv: Path):
        if not pois_csv.exists():
            sys.exit(f"[error] {pois_csv} 없음 — gun/data/에 pois_processed.csv 필요")
        print(f"[load] {pois_csv}")
        df = pd.read_csv(pois_csv, encoding="utf-8-sig", low_memory=False)
        # title 정규화 (공백·특수문자 제거)
        df["_norm"] = df["title"].astype(str).str.strip().str.lower()
        df["_norm_compact"] = df["_norm"].str.replace(r"\s+", "", regex=True)
        self._df = df
        # 인덱스: 정확 매칭용
        self._exact_index: dict[str, int] = {}
        for idx, val in enumerate(df["_norm_compact"]):
            self._exact_index.setdefault(val, idx)
        print(f"  → {len(df):,} POI 로드 완료")

    def match(self, name: str, sido: str = "", sigungu: str = "") -> dict | None:
        """이름으로 매칭. 시도/시군구는 부분 매칭 시 후보 좁히기."""
        if not name:
            return None
        norm = "".join(str(name).strip().lower().split())

        # 1) 정확 매칭
        if norm in self._exact_index:
            row = self._df.iloc[self._exact_index[norm]]
            return self._row_to_dict(row, "exact")

        # 2) 부분 매칭 (포함 관계)
        candidates = self._df[self._df["_norm_compact"].str.contains(norm, na=False, regex=False)]
        if not candidates.empty:
            # 시군구 일치 후보가 있으면 우선
            if sigungu:
                sg_match = candidates[candidates["sigungu"].astype(str).str.contains(sigungu.strip(), na=False)]
                if not sg_match.empty:
                    return self._row_to_dict(sg_match.iloc[0], "partial+sigungu")
            return self._row_to_dict(candidates.iloc[0], "partial")

        # 3) 매칭 실패
        return None

    def _row_to_dict(self, row: Any, status: str) -> dict:
        return {
            "matched_title": row["title"],
            "contentid": row["contentid"],
            "contenttypeid": int(row["contenttypeid"]) if pd.notna(row["contenttypeid"]) else None,
            "lclsSystm1": row.get("lclsSystm1", "") if pd.notna(row.get("lclsSystm1", "")) else "",
            "lclsSystm3": row.get("lclsSystm3", "") if pd.notna(row.get("lclsSystm3", "")) else "",
            "mapx": float(row["mapx"]) if pd.notna(row["mapx"]) else None,
            "mapy": float(row["mapy"]) if pd.notna(row["mapy"]) else None,
            "매칭상태": status,
        }


# ────────────────────────────────────────────────────────────────────
# 2. 일정 단위 처리
# ────────────────────────────────────────────────────────────────────
def _to_vrptw_place(row: dict, dwell_min: int) -> VRPTWPlace | None:
    """매칭된 row → VRPTWPlace 변환. 좌표 없으면 None."""
    if row.get("mapx") is None or row.get("mapy") is None:
        return None
    return VRPTWPlace(
        name=str(row["matched_title"]) if row.get("matched_title") else str(row.get("여행지명", "")),
        lng=float(row["mapx"]),
        lat=float(row["mapy"]),
        open=DEFAULT_OPEN,
        close=DEFAULT_CLOSE,
        stay_duration=dwell_min,
        is_depot=False,
    )


def process_one_day(
    rows: list[dict],
    matrix,
) -> list[dict]:
    """한 day(같은 plan_id+day)의 row들에 이동시간·패널티 채우기."""
    # 매칭된 장소 → VRPTWPlace 리스트
    places: list[VRPTWPlace | None] = []
    for r in rows:
        dwell = r.get("체류시간_분") or 60
        places.append(_to_vrptw_place(r, dwell))

    # 인접 두 장소 간 이동시간 (둘 다 좌표 있어야)
    travel_minutes: list[float | None] = []
    for i in range(len(places) - 1):
        if places[i] is None or places[i + 1] is None:
            travel_minutes.append(None)
            continue
        sec = matrix.get_travel_time(places[i], places[i + 1])
        travel_minutes.append(round(sec / 60.0, 1))
    travel_minutes.append(None)   # 마지막 장소는 다음 이동시간 없음

    # 합계
    total_dwell = sum((r.get("체류시간_분") or 0) for r in rows)
    total_travel = sum((t or 0) for t in travel_minutes)
    total_time = total_dwell + total_travel

    # 패널티 — cluster_dispersion + travel_ratio
    valid_places = [p for p in places if p is not None]
    sigungu_codes = [str(r.get("시군구", "")) for r in rows if r.get("시군구")]

    cluster_pen = 0
    travel_ratio = 0.0
    travel_ratio_penalty = 0
    vrptw_warnings: list[str] = []

    if len(valid_places) >= 2:
        # cluster_dispersion (per-day)
        try:
            day = VRPTWDay(places=valid_places)
            report = evaluate_cluster_dispersion([day], sigungu_codes_per_day=[sigungu_codes])
            cluster_pen = report.total_penalty
            for d in report.deep_dive:
                vrptw_warnings.append(f"{d.rule}({d.risk})")
        except Exception as e:
            vrptw_warnings.append(f"cluster_err:{type(e).__name__}")

        # travel_ratio
        try:
            tr_report = evaluate_travel_ratio([VRPTWDay(places=valid_places)], matrix=matrix)
            travel_ratio = tr_report.overall_ratio
            travel_ratio_penalty = tr_report.total_penalty
        except Exception as e:
            vrptw_warnings.append(f"tr_err:{type(e).__name__}")

    risk_score = max(0, 100 - cluster_pen - travel_ratio_penalty)

    # row별로 결과 채우기
    for i, r in enumerate(rows):
        r["다음장소_이동시간_분"]  = travel_minutes[i]
        r["총_체류시간_분"]        = total_dwell
        r["총_이동시간_분"]        = round(total_travel, 1)
        r["총_일정시간_분"]        = round(total_time, 1)
        r["risk_score"]           = risk_score
        r["travel_ratio"]         = round(travel_ratio, 3)
        r["cluster_penalty"]      = cluster_pen
        r["vrptw_warnings"]       = "; ".join(vrptw_warnings) if vrptw_warnings else ""

    return rows


# ────────────────────────────────────────────────────────────────────
# 3. 메인 파이프라인
# ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_XLSX), help="입력 Excel 경로")
    parser.add_argument("--output-dir", default=str(DATA_DIR), help="출력 폴더")
    parser.add_argument("--no-kakao", action="store_true",
                        help="Kakao 호출 스킵 (Haversine 폴백만 사용 — API 한도 절약)")
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        sys.exit(f"[error] 입력 파일 없음: {input_path}\n"
                 f"  → 먼저 {INPUT_XLSX} 양식을 채우세요.")

    print(f"\n[1/4] 입력 로드: {input_path}")
    df_in = pd.read_excel(input_path, sheet_name=0, dtype=str).fillna("")
    df_in.columns = [c.strip() for c in df_in.columns]

    # 필수 컬럼 검증
    missing = [c for c in INPUT_COLS if c not in df_in.columns and c != "카테고리힌트"]
    if missing:
        sys.exit(f"[error] 입력에 필수 컬럼 누락: {missing}")
    print(f"  → {len(df_in)}개 row 로드")

    # ── 2/4: POI 매칭 ──
    print(f"\n[2/4] POI 매칭 (pois_processed.csv 기반)")
    matcher = POIMatcher(POIS_CSV)
    failed: list[dict] = []
    rows: list[dict] = []
    for _, raw in df_in.iterrows():
        r = {col: raw.get(col, "") for col in INPUT_COLS}
        m = matcher.match(r["여행지명"], r.get("시도", ""), r.get("시군구", ""))
        if m:
            r.update(m)
        else:
            r["매칭상태"] = "not_found"
            r["matched_title"] = ""
            r["contentid"]    = ""
            r["contenttypeid"]= None
            r["lclsSystm1"]   = ""
            r["lclsSystm3"]   = ""
            r["mapx"]         = None
            r["mapy"]         = None
            failed.append({"plan_id": r["plan_id"], "여행지명": r["여행지명"],
                           "시도": r["시도"], "시군구": r["시군구"]})

        # 체류시간 (dwell_db 5단계 폴백)
        rec = get_recommended_dwell(
            name=r.get("matched_title") or r["여행지명"],
            lcls_systm3=r.get("lclsSystm3") or None,
            lcls_systm1=r.get("lclsSystm1") or None,
            content_type_id=r.get("contenttypeid"),
        )
        r["체류시간_분"] = rec.min_minutes
        r["체류출처"]    = rec.source

        rows.append(r)

    n_total = len(rows)
    n_failed = len(failed)
    fail_pct = n_failed / n_total * 100 if n_total else 0
    print(f"  → 매칭: 성공 {n_total - n_failed}개, 실패 {n_failed}개 ({fail_pct:.1f}%)")
    if fail_pct > 10:
        print(f"  ⚠️ 실패율 10% 초과 — match_failed.csv 확인 후 이름 보정 권장")

    # 매칭 실패 별도 저장
    if failed:
        with open(FAILED_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["plan_id", "여행지명", "시도", "시군구"])
            w.writeheader()
            w.writerows(failed)
        print(f"  → {FAILED_CSV.name} 저장")

    # ── 3/4: 일정 단위 시간/패널티 계산 ──
    print(f"\n[3/4] 이동시간 + 패널티 계산")
    if args.no_kakao:
        print("  (--no-kakao 모드 — Haversine 폴백만 사용)")
        matrix = HaversineMatrix()
    else:
        matrix = KakaoMobilityMatrix.from_env(cache_path=CACHE_JSON)
        print(f"  Kakao 캐시: {CACHE_JSON.name} ({matrix.cache_size} 항목)")

    # plan_id + day로 그룹핑
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["plan_id"], r.get("day", "1"))
        grouped[key].append(r)

    # 방문순서로 정렬 후 처리
    processed: list[dict] = []
    for key, day_rows in grouped.items():
        day_rows.sort(key=lambda x: int(x.get("방문순서", 0) or 0))
        processed.extend(process_one_day(day_rows, matrix))

    # Kakao 캐시 저장
    if not args.no_kakao:
        matrix.save_cache()
        print(f"  → Kakao 통계: {matrix.stats}")

    # ── 4/4: Excel 출력 ──
    today = _date.today().strftime("%Y%m%d")
    out_path = out_dir / f"itinerary_results_{today}.xlsx"
    print(f"\n[4/4] Excel 출력: {out_path}")

    df_out = pd.DataFrame(processed, columns=OUTPUT_COLS)
    # 보기 좋게 정렬
    df_out = df_out.sort_values(["plan_id", "day", "방문순서"], ignore_index=True)
    df_out.to_excel(out_path, index=False, sheet_name="results")
    print(f"  → {len(df_out)}개 row 저장 완료")

    # 요약
    print(f"\n[summary]")
    print(f"  총 일정 수: {df_out['plan_id'].nunique()}")
    print(f"  총 장소 수: {len(df_out)}")
    print(f"  매칭 실패율: {fail_pct:.1f}%")
    if "risk_score" in df_out.columns:
        print(f"  평균 risk_score: {df_out['risk_score'].mean():.1f}")
    print(f"  결과 파일: {out_path}")


if __name__ == "__main__":
    main()
