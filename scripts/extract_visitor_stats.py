"""PDF 전처리 스크립트: 한국문화관광연구원 주요관광지점 입장객 통계 (2020-2024)

Usage:
    python scripts/extract_visitor_stats.py
    python scripts/extract_visitor_stats.py --output data/congestion_stats.csv
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import pdfplumber

DATA_DIR = Path(__file__).parent.parent / "data" / "한국문화관광연구원"
DEFAULT_OUT = Path(__file__).parent.parent / "data" / "congestion_stats.csv"

PDF_FILES = {
    2020: "2020년_주요관광지점_입장객_통계집.pdf",
    2021: "2021년_주요관광지점_입장객_통계집.pdf",
    2022: "2022년_주요관광지점_입장객통계집.pdf",
    2023: "2023년_주요관광지점_입장객_통계집.pdf",
    2024: "2024년_주요관광지점_입장객_통계집.pdf",
}

MONTH_COLS = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
EXPECTED_HEADER_TOKENS = {"관광지", "구분", "1월", "12월"}


def _parse_int(val: str | None) -> float | None:
    """'1,234,567' or '-' → float or None."""
    if val is None:
        return None
    cleaned = re.sub(r"[,\s]", "", str(val).strip())
    if cleaned in ("-", "", "무응답"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_header_row(row: list) -> bool:
    cells = {str(c).strip() for c in row if c}
    return len(cells & EXPECTED_HEADER_TOKENS) >= 3


def extract_year(pdf_path: Path, year: int) -> pd.DataFrame:
    """한 연도 PDF에서 관광지별 '계' 행만 추출 → long 포맷 DataFrame."""
    records: list[dict] = []
    current_spot = None

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                if not _is_header_row(table[0]):
                    continue
                for raw_row in table[1:]:
                    if len(raw_row) < 16:
                        continue
                    # col 2: 관광지명 (only filled on first of 3 sub-rows)
                    spot = str(raw_row[2]).strip().replace("\n", " ") if raw_row[2] else None
                    if spot and spot not in ("-", ""):
                        current_spot = spot
                    category = str(raw_row[3]).strip() if raw_row[3] else ""
                    # Only keep '계' rows (total)
                    if category != "계" or current_spot is None:
                        continue
                    monthly: dict[str, float | None] = {}
                    for idx, label in enumerate(MONTH_COLS, start=6):
                        if idx < len(raw_row):
                            monthly[label] = _parse_int(raw_row[idx])
                    records.append({"poi_name": current_spot, "year": year, **monthly})

    df = pd.DataFrame(records)
    if df.empty:
        print(f"  [WARNING] {year}: no records extracted")
    else:
        print(f"  {year}: {len(df)} POI-year records")
    return df


def compute_congestion(df_raw: pd.DataFrame) -> pd.DataFrame:
    """5개년 raw 데이터 → poi_name × month 집계 및 congestion_score 산출."""
    # Wide → long
    long = df_raw.melt(
        id_vars=["poi_name", "year"],
        value_vars=MONTH_COLS,
        var_name="month_label",
        value_name="visitors",
    )
    long["month"] = long["month_label"].str.replace("월", "").astype(int)
    long = long.dropna(subset=["visitors"])
    long["visitors"] = long["visitors"].astype(float)

    # Monthly avg across years per POI
    monthly_avg = (
        long.groupby(["poi_name", "month"])["visitors"]
        .mean()
        .reset_index()
        .rename(columns={"visitors": "avg_visitors"})
    )

    # Annual avg (mean of 12 monthly avgs) per POI
    annual_avg = monthly_avg.groupby("poi_name")["avg_visitors"].mean().rename("annual_monthly_avg")
    monthly_avg = monthly_avg.join(annual_avg, on="poi_name")

    # Seasonal index = monthly / annual_avg; normalize per POI to [0, 1]
    monthly_avg["seasonal_index"] = monthly_avg["avg_visitors"] / monthly_avg["annual_monthly_avg"].replace(0, float("nan"))
    max_idx = monthly_avg.groupby("poi_name")["seasonal_index"].transform("max")
    monthly_avg["congestion_score"] = (monthly_avg["seasonal_index"] / max_idx).clip(0.0, 1.0).round(4)

    # Annual stats
    ann_stats = (
        long.groupby(["poi_name", "year"])["visitors"]
        .sum()
        .reset_index()
    )
    ann_agg = ann_stats.groupby("poi_name")["visitors"].agg(
        annual_max="max", annual_min="min"
    ).reset_index()

    result = monthly_avg[["poi_name", "month", "avg_visitors", "congestion_score"]].merge(
        ann_agg, on="poi_name", how="left"
    )
    result["avg_visitors"] = result["avg_visitors"].round(1)
    return result.sort_values(["poi_name", "month"]).reset_index(drop=True)


def main(output: Path = DEFAULT_OUT) -> None:
    print("=== 주요관광지점 입장객 통계 전처리 시작 ===")
    frames: list[pd.DataFrame] = []
    for year, fname in PDF_FILES.items():
        path = DATA_DIR / fname
        if not path.exists():
            print(f"  [SKIP] {path} not found")
            continue
        print(f"[{year}] {fname}")
        frames.append(extract_year(path, year))

    if not frames:
        print("ERROR: PDF 파일을 찾을 수 없습니다.")
        return

    raw = pd.concat(frames, ignore_index=True)
    print(f"\nRaw records: {len(raw)} rows, {raw['poi_name'].nunique()} unique POIs")

    result = compute_congestion(raw)
    print(f"Output: {len(result)} rows, {result['poi_name'].nunique()} unique POIs")

    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {output}")

    # Summary
    sample = result[result["poi_name"] == result["poi_name"].iloc[0]]
    print(f"\n샘플 ({sample['poi_name'].iloc[0]}):")
    print(sample[["month", "avg_visitors", "congestion_score"]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    main(args.output)
