"""POI CSV 종합 전처리
=========================
TourAPI 원본 CSV에 대해 세 가지 변환을 한 번에 적용:

1. addr1 (예: "강원특별자치도 강릉시 옥계면 금진리")
     → sido / sigungu / dong_or_road  (시도 / 시군구 / 읍면동·도로명)

2. dong_or_road (예: "청계면 사마리" / "포곡읍 에버랜드로 199")
     → eup_myeon / ri  (띄어쓰기 1번째→eup_myeon, 2번째→ri, 3번째 이후는 drop)

3. createdtime, modifiedtime (예: "20260422110725")
     → {prefix}_date (YYYY-MM-DD) / _year / _month  (day, time 제외)

나머지 컬럼은 그대로 유지.

사용법
------
    python3 scripts/preprocess_pois.py                          # 기본: data/pois.csv
    python3 scripts/preprocess_pois.py data/pois.csv -o data/pois_clean.csv
    python3 scripts/preprocess_pois.py --keep-original          # 원본 컬럼도 보존
    python3 scripts/preprocess_pois.py --keep-dong-or-road      # dong_or_road 보존
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


# ── 한국 주소 파서 ────────────────────────────────────────────────────
# 시군구 끝글자 (1단계 시군구 식별용)
_SIGUNGU_SUFFIX: tuple[str, ...] = ("시", "군", "구")


def parse_korean_address(addr: str | float | None) -> tuple[str, str, str]:
    """한국 주소 문자열 → (시도, 시군구, 읍면동·도로명) 분리.

    규칙
    ----
    1. 첫 토큰 = 시도 (어떤 형태든 그대로)
    2. 시군구는 1~2 토큰:
       - "성남시 분당구", "청주시 흥덕구" 패턴 (시+구) → 2 토큰 결합
       - 단일 "남양주시", "울주군", "강남구" → 1 토큰
       - 세종특별자치시처럼 시군구 없는 경우 → 빈 문자열
    3. 나머지 모두 = 읍면동·도로명+번지 (괄호 표기 포함)

    예시
    ----
    >>> parse_korean_address("경기도 남양주시 송산로 196-4")
    ('경기도', '남양주시', '송산로 196-4')
    >>> parse_korean_address("충청북도 청주시 흥덕구 짐대로 62 (복대동)")
    ('충청북도', '청주시 흥덕구', '짐대로 62 (복대동)')
    >>> parse_korean_address("강원특별자치도 양양군 현남면 동산리")
    ('강원특별자치도', '양양군', '현남면 동산리')
    >>> parse_korean_address("세종특별자치시 한솔동")
    ('세종특별자치시', '', '한솔동')
    """
    if not addr or pd.isna(addr):
        return "", "", ""
    s = str(addr).strip()
    if not s:
        return "", "", ""

    tokens = s.split()
    if not tokens:
        return "", "", ""

    sido = tokens[0]
    rest = tokens[1:]
    if not rest:
        return sido, "", ""

    # 2-토큰 시군구 (시 + 구) 패턴 우선 시도
    if (len(rest) >= 2
            and rest[0].endswith("시")
            and rest[1].endswith("구")):
        sigungu = f"{rest[0]} {rest[1]}"
        tail = rest[2:]
    elif rest[0].endswith(_SIGUNGU_SUFFIX):
        sigungu = rest[0]
        tail = rest[1:]
    else:
        # 시군구 없는 직할시(세종 등)
        sigungu = ""
        tail = rest

    return sido, sigungu, " ".join(tail)


def split_address_columns(
    df: pd.DataFrame,
    column: str = "addr1",
    keep_original: bool = False,
) -> pd.DataFrame:
    if column not in df.columns:
        print(f"  [skip] '{column}' 컬럼 없음")
        return df

    parts = df[column].apply(parse_korean_address)
    df["sido"]         = parts.apply(lambda t: t[0])
    df["sigungu"]      = parts.apply(lambda t: t[1])
    df["dong_or_road"] = parts.apply(lambda t: t[2])

    n_total = len(df)
    n_sido    = (df["sido"] != "").sum()
    n_sigungu = (df["sigungu"] != "").sum()
    n_dong    = (df["dong_or_road"] != "").sum()
    print(f"  · {column}: 시도 {n_sido:,}/{n_total:,} ({n_sido/n_total:.1%}) | "
          f"시군구 {n_sigungu:,}/{n_total:,} | "
          f"읍면동·도로명 {n_dong:,}/{n_total:,}")

    if not keep_original:
        df = df.drop(columns=[column])
    return df


# ── eup_myeon / ri 추가 분리 ─────────────────────────────────────────
def parse_eup_myeon_ri(text: str | float | None) -> tuple[str, str]:
    """dong_or_road를 띄어쓰기로 분리 — 1번째 → eup_myeon, 2번째 → ri.
    3번째 이후 토큰은 모두 drop ('리 단위 이하' 제거).

    예시
    ----
    >>> parse_eup_myeon_ri("청계면 사마리")
    ('청계면', '사마리')
    >>> parse_eup_myeon_ri("강진읍 고성길 174")
    ('강진읍', '고성길')
    >>> parse_eup_myeon_ri("번영로 2350-104")
    ('번영로', '2350-104')
    >>> parse_eup_myeon_ri("명동로 62")
    ('명동로', '62')
    >>> parse_eup_myeon_ri("")
    ('', '')
    """
    if not text or pd.isna(text):
        return "", ""
    s = str(text).strip()
    if not s:
        return "", ""
    tokens = s.split()
    if not tokens:
        return "", ""
    eup_myeon = tokens[0]
    ri = tokens[1] if len(tokens) >= 2 else ""
    return eup_myeon, ri


def split_eup_myeon_ri_columns(
    df: pd.DataFrame,
    column: str = "dong_or_road",
    keep_original: bool = False,
) -> pd.DataFrame:
    if column not in df.columns:
        print(f"  [skip] '{column}' 컬럼 없음")
        return df

    parts = df[column].apply(parse_eup_myeon_ri)
    df["eup_myeon"] = parts.apply(lambda t: t[0])
    df["ri"]        = parts.apply(lambda t: t[1])

    n_total = len(df)
    n_em = (df["eup_myeon"] != "").sum()
    n_ri = (df["ri"] != "").sum()
    print(f"  · {column}: eup_myeon {n_em:,}/{n_total:,} ({n_em/n_total:.1%}) | "
          f"ri {n_ri:,}/{n_total:,} ({n_ri/n_total:.1%})")

    if not keep_original:
        df = df.drop(columns=[column])
    return df


# ── 날짜 파서 ────────────────────────────────────────────────────────
def split_date_columns(
    df: pd.DataFrame,
    column: str,
    prefix: str,
    keep_original: bool = False,
) -> pd.DataFrame:
    """YYYYMMDDHHMMSS → {prefix}_date / _year / _month (day, time 제외)."""
    if column not in df.columns:
        print(f"  [skip] '{column}' 컬럼 없음")
        return df

    s = df[column].astype(str).str.zfill(14)
    valid = s.str.match(r"^\d{14}$")
    n_valid = int(valid.sum())
    n_total = len(df)
    print(f"  · {column}: 유효 {n_valid:,}/{n_total:,} ({n_valid/n_total:.1%})")

    df[f"{prefix}_date"]  = (s.str[:4] + "-" + s.str[4:6] + "-" + s.str[6:8]).where(valid, "")
    df[f"{prefix}_year"]  = pd.to_numeric(s.str[:4],  errors="coerce").astype("Int64")
    df[f"{prefix}_month"] = pd.to_numeric(s.str[4:6], errors="coerce").astype("Int64")

    if not keep_original:
        df = df.drop(columns=[column])
    return df


# ── 메인 파이프라인 ──────────────────────────────────────────────────
def preprocess(
    input_csv: Path,
    output_csv: Path,
    keep_original: bool = False,
    keep_dong_or_road: bool = False,
) -> None:
    print(f"\n[입력] {input_csv}")
    df = pd.read_csv(
        input_csv,
        encoding="utf-8-sig",
        dtype={
            "createdtime":  str,
            "modifiedtime": str,
            "zipcode":      str,
            "tel":          str,
        },
        low_memory=False,
    )
    print(f"  → 행 {len(df):,}, 컬럼 {len(df.columns)}")

    print(f"\n[변환 1/3] addr1 → sido / sigungu / dong_or_road")
    df = split_address_columns(df, "addr1", keep_original=keep_original)

    print(f"\n[변환 2/3] dong_or_road → eup_myeon / ri (3번째 토큰 이후 drop)")
    df = split_eup_myeon_ri_columns(
        df, "dong_or_road",
        keep_original=keep_original or keep_dong_or_road,
    )

    print(f"\n[변환 3/3] createdtime/modifiedtime → date/year/month")
    df = split_date_columns(df, "createdtime",  "created",  keep_original=keep_original)
    df = split_date_columns(df, "modifiedtime", "modified", keep_original=keep_original)

    # 컬럼 순서: 핵심 식별자 → 주소(상→하 계층) → lDong/분류 → 좌표 → 부가 → 날짜
    address_cols = [c for c in ["sido", "sigungu", "dong_or_road",
                                "eup_myeon", "ri"] if c in df.columns]
    date_cols    = [c for c in df.columns
                    if c.startswith(("created_", "modified_"))]
    others       = [c for c in df.columns
                    if c not in set(address_cols + date_cols)]

    # addr2 직전에 주소 컬럼들 삽입
    if "addr2" in others:
        idx = others.index("addr2")
        new_order = others[:idx] + address_cols + others[idx:]
    else:
        new_order = others + address_cols
    df = df[new_order + date_cols]

    print(f"\n[저장] {output_csv}")
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"  → 행 {len(df):,}, 컬럼 {len(df.columns)}")
    print(f"  → 컬럼: {list(df.columns)}")

    # 미리보기 + 요약
    print(f"\n[샘플 8건 — 핵심 컬럼만]")
    preview_cols = [c for c in [
        "title", "sido", "sigungu", "eup_myeon", "ri",
        "created_year", "modified_year",
    ] if c in df.columns]
    print(df[preview_cols].head(8).to_string(index=False))

    if "sido" in df.columns:
        print(f"\n[sido 분포 상위 10]")
        print(df["sido"].value_counts().head(10).to_string())

    if "modified_year" in df.columns:
        print(f"\n[modified_year 분포]")
        print(df["modified_year"].value_counts().sort_index().to_string())


def main() -> None:
    parser = argparse.ArgumentParser(description="POI CSV 종합 전처리 (주소+날짜)")
    parser.add_argument("input", nargs="?", default="data/pois.csv",
                        help="입력 CSV (기본: data/pois.csv)")
    parser.add_argument("-o", "--output", default="",
                        help="출력 CSV (기본: 입력파일명_processed.csv)")
    parser.add_argument("--keep-original", action="store_true",
                        help="addr1, dong_or_road, createdtime, modifiedtime 원본 모두 유지")
    parser.add_argument("--keep-dong-or-road", action="store_true",
                        help="dong_or_road만 유지 (도로명·번지 정보 보존)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"[error] 입력 파일 없음: {input_path}")

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_processed{input_path.suffix}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    preprocess(
        input_path, output_path,
        keep_original=args.keep_original,
        keep_dong_or_road=args.keep_dong_or_road,
    )


if __name__ == "__main__":
    main()
