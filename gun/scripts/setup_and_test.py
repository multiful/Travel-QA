"""env 생성 + Kakao API 테스트.

⚠️ 키는 절대 코드에 하드코딩하지 말 것 — 환경변수 또는 .env 파일에서 읽어옴.

사용법:
    1. 프로젝트 루트의 .env.example 을 .env 로 복사
    2. .env 안의 각 키에 본인 값 입력
    3. python3 gun/scripts/setup_and_test.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"

# ── 1. .env 존재 확인 ───────────────────────────────────────────
if not ENV_PATH.exists():
    print("[error] .env 가 없습니다.")
    print(f"        다음을 실행하세요:")
    print(f"          cp {PROJECT_ROOT}/.env.example {ENV_PATH}")
    print(f"        그 후 .env 안의 각 키에 본인 값 입력.")
    sys.exit(1)

# python-dotenv 가 설치돼 있으면 사용, 아니면 수동 파싱
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

# ── 2. 필수 키 확인 ────────────────────────────────────────────
REQUIRED = ("KAKAO_MOBILITY_KEY",)
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    print(f"[error] .env 에 다음 키가 비어 있습니다: {', '.join(missing)}")
    sys.exit(1)

# ── 3. Kakao Mobility 호출 테스트 ──────────────────────────────
sys.path.insert(0, str(PROJECT_ROOT))
from src.validation.kakao_matrix import KakaoMobilityMatrix
from src.data.models import VRPTWPlace

print("[test] Kakao API 호출 중...")
m = KakaoMobilityMatrix.from_env()
a = VRPTWPlace(name="경복궁",       lng=126.977, lat=37.579, open="09:00", close="18:00", stay_duration=90)
b = VRPTWPlace(name="남산서울타워", lng=126.988, lat=37.551, open="10:00", close="22:00", stay_duration=90)

duration = m.get_travel_time(a, b)
print(f"경복궁 → 남산서울타워: {duration}초 ({duration/60:.1f}분)")
print(f"통계: {m.stats}")

if m.stats["api_success"] >= 1:
    print("\n✅ Kakao Mobility API 정상 작동!")
elif m.stats["fallback"] >= 1:
    print("\n⚠️ API 호출 실패 → Haversine 폴백 사용")
