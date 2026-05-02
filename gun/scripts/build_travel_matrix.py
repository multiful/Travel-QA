"""POI CSV → 카카오 모빌리티 N×N 이동시간 행렬 사전 빌드.

검증 시 매번 API를 호출하면 느리고 한도 부담. 자주 쓰는 POI 세트(예:
구석구석/트리플 추천 50~100건)는 미리 페어와이즈 거리를 다 받아 캐시화.

사용법
------
    # 1. 작은 샘플 먼저 (10개 POI = 90회 호출)
    python3 scripts/build_travel_matrix.py \\
        --poi-csv data/sample_pois.csv --limit 10

    # 2. CSV 컬럼명이 다를 때 (lng/lat 컬럼명 명시)
    python3 scripts/build_travel_matrix.py \\
        --poi-csv data/pois.csv \\
        --x-col mapx --y-col mapy --name-col title --limit 30

    # 3. 일정 입력에서 등장한 POI만 추출 후 행렬 빌드
    python3 scripts/build_travel_matrix.py \\
        --poi-csv data/itinerary_pois.csv

산출물
------
    data/route_cache.json   # KakaoMobilityMatrix가 그대로 사용 가능
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# gun/scripts/X.py 에서 실제 프로젝트 루트는 parents[2] (portfolio/travel/)
# parents[0]=scripts, parents[1]=gun, parents[2]=portfolio/travel
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.data.models import VRPTWPlace                       # noqa: E402
from src.validation.kakao_matrix import KakaoMobilityMatrix  # noqa: E402


def _resolve_base_dir() -> Path:
    try:
        return Path(__file__).resolve().parent.parent
    except NameError:
        cwd = Path.cwd()
        return cwd.parent if cwd.name == "scripts" else cwd


BASE_DIR = _resolve_base_dir()
DEFAULT_CACHE = BASE_DIR / "data" / "route_cache.json"


def load_pois(
    csv_path: Path,
    x_col: str,
    y_col: str,
    name_col: str,
    limit: int | None,
) -> list[VRPTWPlace]:
    """CSV 읽어 좌표 유효한 POI 리스트로 반환."""
    out: list[VRPTWPlace] = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lng = float(row[x_col])
                lat = float(row[y_col])
            except (KeyError, ValueError, TypeError):
                continue
            name = (row.get(name_col) or "").strip() or f"POI_{len(out)}"
            # VRPTWPlace는 open/close 검증이 있어 더미 시간 채움
            out.append(VRPTWPlace(
                name=name, lng=lng, lat=lat,
                open="00:00", close="23:59", stay_duration=0, is_depot=False,
            ))
            if limit and len(out) >= limit:
                break
    return out


def build_matrix(
    pois: list[VRPTWPlace],
    matrix: KakaoMobilityMatrix,
    sleep_between: float = 0.05,
) -> None:
    """N×N 페어와이즈 호출 (대각선 제외, 양방향 캐시 활용)."""
    n = len(pois)
    total_pairs = n * (n - 1) // 2     # 양방향 캐시로 절반만 호출
    print(f"[start] N={n}, 호출 예상 최대 {total_pairs}회 "
          f"(대칭 캐시로 절반만 실호출)")

    done = 0
    start_ts = time.time()
    for i in range(n):
        for j in range(i + 1, n):
            matrix.get_travel_time(pois[i], pois[j])
            done += 1

            # 한도 소진 시 즉시 중단
            if matrix.is_quota_exhausted:
                print(f"\n[quota] 일일 한도 도달 — {done}/{total_pairs}쌍 진행 후 중단")
                matrix.save_cache()
                return

            if done % 20 == 0:
                elapsed = time.time() - start_ts
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total_pairs - done) / rate if rate > 0 else 0
                stats = matrix.stats
                print(f"  [{done}/{total_pairs}] "
                      f"hit={stats['cache_hit']} api={stats['api_success']} "
                      f"fail={stats['api_fail']} fallback={stats['fallback']} "
                      f"({rate:.1f}/s, ETA {eta:.0f}s)")

            time.sleep(sleep_between)

    matrix.save_cache()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="카카오 모빌리티 사전 행렬 빌더",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--poi-csv", required=True,
        help="입력 CSV 경로",
    )
    parser.add_argument(
        "--x-col", default="mapx",
        help="경도(longitude) 컬럼명 (기본: mapx)",
    )
    parser.add_argument(
        "--y-col", default="mapy",
        help="위도(latitude) 컬럼명 (기본: mapy)",
    )
    parser.add_argument(
        "--name-col", default="title",
        help="POI 이름 컬럼명 (기본: title)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="처음 N개 POI만 사용 (테스트용)",
    )
    parser.add_argument(
        "--cache", default=str(DEFAULT_CACHE),
        help=f"캐시 JSON 경로 (기본: {DEFAULT_CACHE.relative_to(BASE_DIR)})",
    )
    parser.add_argument(
        "--sleep", type=float, default=0.05,
        help="호출 간 대기(초). Kakao QPS 제어 (기본 0.05 = 20 RPS)",
    )
    args = parser.parse_args()

    csv_path = Path(args.poi_csv)
    if not csv_path.is_absolute():
        csv_path = BASE_DIR / csv_path
    if not csv_path.exists():
        sys.exit(f"[error] CSV 없음: {csv_path}")

    print(f"[load] {csv_path}")
    pois = load_pois(
        csv_path,
        x_col=args.x_col, y_col=args.y_col, name_col=args.name_col,
        limit=args.limit,
    )
    print(f"  → {len(pois)}개 POI 로드")
    if len(pois) < 2:
        sys.exit("[error] POI가 2개 미만 — 행렬 계산 불가")

    cache_path = Path(args.cache)
    if not cache_path.is_absolute():
        cache_path = BASE_DIR / cache_path

    matrix = KakaoMobilityMatrix.from_env(
        cache_path=cache_path,
        sleep_between=args.sleep,
    )
    print(f"[cache] {cache_path} (기존 {matrix.cache_size}개)")

    try:
        build_matrix(pois, matrix, sleep_between=args.sleep)
    except KeyboardInterrupt:
        print("\n[중단] Ctrl+C — 캐시 저장 후 종료")
        matrix.save_cache()
    except Exception as e:
        print(f"\n[error] {type(e).__name__}: {e}")
        matrix.save_cache()
        raise

    stats = matrix.stats
    print(f"\n[완료] 캐시 {matrix.cache_size}개 보유 ({cache_path})")
    print(f"  cache_hit={stats['cache_hit']} "
          f"api_success={stats['api_success']} "
          f"api_fail={stats['api_fail']} "
          f"fallback={stats['fallback']}")


if __name__ == "__main__":
    main()
