"""
AI 여행 추천 성능 통계 분석
analysis_result.json 을 읽어 AI 추천의 구조적 문제를 정량화한다.
"""
import json
import math
import statistics
import sys
from pathlib import Path
from collections import defaultdict

# Windows 콘솔 UTF-8 출력 강제
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
data = json.loads((BASE / "analysis_result.json").read_text(encoding="utf-8"))
entries = data["entries"]

# ── 임계값 ───────────────────────────────────────────────────────────────
TRAVEL_WARN  = 0.20   # 이동 비율 경고 임계값
TRAVEL_CRIT  = 0.40   # 이동 비율 위험 임계값
DIST_CRIT_KM = 50.0   # 같은 날 최대 직선거리 위험 임계값 (km)

# ── 기본 집계 ────────────────────────────────────────────────────────────
total_days   = len(entries)
valid_route  = [e for e in entries if e["travel_ratio"] is not None]
no_route     = [e for e in entries if e["travel_ratio"] is None]

tr_vals      = [e["travel_ratio"] for e in valid_route]
dist_vals    = [e["max_dist_km"] for e in entries if e["max_dist_km"] > 0]
dur_vals     = [e["total_hr"] for e in entries if e["total_sec"] > 0]
bt_vals      = [e["backtrack"] for e in entries]

def pct(num, den):
    return round(num / den * 100, 1) if den else 0

def pctile(data, p):
    data = sorted(data)
    idx  = (len(data) - 1) * p / 100
    lo   = int(idx)
    hi   = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (idx - lo)

# ── 임계값 초과 분류 ─────────────────────────────────────────────────────
warn_days = [e for e in valid_route if e["travel_ratio"] >= TRAVEL_WARN]
crit_days = [e for e in valid_route if e["travel_ratio"] >= TRAVEL_CRIT]
dist_crit = [e for e in entries     if e["max_dist_km"] >= DIST_CRIT_KM]

# ── 여행 기간별 집계 ─────────────────────────────────────────────────────
by_dur = defaultdict(list)
for e in valid_route:
    by_dur[e["duration"]].append(e["travel_ratio"])

# ── 지역별 집계 ─────────────────────────────────────────────────────────
by_region = defaultdict(list)
for e in valid_route:
    by_region[e["region"]].append(e["travel_ratio"])

# 지역별 평균, 내림차순 정렬
region_avg = {r: round(statistics.mean(v), 3) for r, v in by_region.items()}
region_sorted = sorted(region_avg.items(), key=lambda x: -x[1])

# ── 심각 이상 경우 ────────────────────────────────────────────────────────
extreme_cases = sorted(
    [e for e in valid_route if e["travel_ratio"] >= 0.30],
    key=lambda x: -x["travel_ratio"]
)
long_dist_cases = sorted(dist_crit, key=lambda x: -x["max_dist_km"])

# ── 경로 데이터 누락 분석 ─────────────────────────────────────────────────
no_route_by_num = defaultdict(list)
for e in no_route:
    no_route_by_num[e["num"]].append(e["day"])

# ── 백트래킹 분석 ─────────────────────────────────────────────────────────
bt_nonzero = [e for e in entries if e["backtrack"] > 0]
bt_by_dur  = defaultdict(list)
for e in entries:
    bt_by_dur[e["duration"]].append(e["backtrack"])

# ── 출력 ─────────────────────────────────────────────────────────────────
sep = "=" * 60

def header(title):
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)

print(f"\n{'='*60}")
print("  AI 여행 추천 성능 통계 보고서")
print(f"  대상: 50개 추천 일정, {total_days}개 day 항목")
print(f"{'='*60}")

# 1. 데이터 품질 현황
header("1. 데이터 품질 현황")
print(f"  경로 데이터 보유    : {len(valid_route):3d}일 / {total_days}일 ({pct(len(valid_route), total_days)}%)")
print(f"  경로 데이터 누락    : {len(no_route):3d}일 / {total_days}일 ({pct(len(no_route), total_days)}%)  ← Kakao API 한도 초과")
print(f"  지오코딩 성공률     : {data['geo_coverage']['hit']}/{data['geo_coverage']['total']} ({pct(data['geo_coverage']['hit'], data['geo_coverage']['total'])}%)")
print(f"  경로 누락 항목 번호 : {sorted(no_route_by_num.keys())}")

# 2. 이동 비율 분포
header("2. 이동 비율(travel_ratio) 분포  [유효 n={n}]".format(n=len(tr_vals)))
print(f"  평균    : {statistics.mean(tr_vals):.3f}  ({statistics.mean(tr_vals)*100:.1f}%)")
print(f"  중앙값  : {statistics.median(tr_vals):.3f}  ({statistics.median(tr_vals)*100:.1f}%)")
print(f"  표준편차: {statistics.stdev(tr_vals):.3f}  (변동계수 CV={statistics.stdev(tr_vals)/statistics.mean(tr_vals):.2f})")
print(f"  P25     : {pctile(tr_vals,25):.3f}    P75: {pctile(tr_vals,75):.3f}    P90: {pctile(tr_vals,90):.3f}")
print(f"  최솟값  : {min(tr_vals):.3f}    최댓값: {max(tr_vals):.3f}")
print()
print(f"  ≥ {TRAVEL_WARN:.0%} (경고): {len(warn_days):2d}일 / {len(valid_route)}일  ({pct(len(warn_days), len(valid_route))}%)  → 전체 일정 20% 이상이 이동")
print(f"  ≥ {TRAVEL_CRIT:.0%} (위험): {len(crit_days):2d}일 / {len(valid_route)}일  ({pct(len(crit_days), len(valid_route))}%)  → 전체 일정 40% 이상이 이동")

# 3. 기간 유형별 비교
header("3. 여행 기간 유형별 이동 비율")
for dur in ["당일여행", "1박 2일", "2박 3일"]:
    vals = by_dur.get(dur, [])
    if not vals:
        continue
    mean_v = statistics.mean(vals)
    med_v  = statistics.median(vals)
    crit_n = sum(1 for v in vals if v >= TRAVEL_CRIT)
    print(f"  {dur:8s}  n={len(vals):2d}  평균={mean_v:.3f}  중앙={med_v:.3f}  위험건수={crit_n}")

# 4. 지역별 이동 비율 (상위 5)
header("4. 지역별 평균 이동 비율 (상위 5 — 이동 과다)")
for region, avg in region_sorted[:5]:
    n = len(by_region[region])
    print(f"  {region:6s}  평균={avg:.3f}  n={n}")

# 5. 심각 사례 (travel_ratio ≥ 0.30)
header("5. 심각 사례  — 이동 비율 ≥ 30%")
print(f"  {'번호':>4}  {'지역':6}  {'기간':8}  {'일차':4}  {'이동비율':8}  {'이동시간':10}  {'총시간':8}")
print(f"  {'-'*65}")
for e in extreme_cases:
    travel_min = e["travel_min"]
    total_hr   = e["total_hr"]
    ratio_str  = f"{e['travel_ratio']:.3f}"
    warn_flag  = "🔴" if e["travel_ratio"] >= TRAVEL_CRIT else "🟡"
    print(f"  {warn_flag} {e['num']:>3}  {e['region']:6}  {e['duration']:8}  D{e['day']}  "
          f"{ratio_str:8}  {travel_min:6.0f}분     {total_hr:.1f}h")

# 6. 지리 분산 (max_dist_km ≥ 50km)
header("6. 지리 분산 이상  — 같은 날 최대 직선거리 ≥ 50km")
print(f"  해당 day: {len(long_dist_cases)}건")
print(f"  {'번호':>4}  {'지역':6}  {'기간':8}  {'일차':4}  {'최대거리(km)':12}  {'이동비율'}")
print(f"  {'-'*60}")
for e in long_dist_cases[:10]:
    ratio_str = f"{e['travel_ratio']:.3f}" if e["travel_ratio"] is not None else "N/A"
    print(f"  {e['num']:>4}  {e['region']:6}  {e['duration']:8}  D{e['day']}  "
          f"{e['max_dist_km']:12.1f}  {ratio_str}")
if len(long_dist_cases) > 10:
    print(f"  ... 외 {len(long_dist_cases)-10}건")

# 7. 백트래킹 (같은 구역 재방문)
header("7. 백트래킹 분석  (같은 5km 격자 재방문)")
print(f"  백트래킹 발생 day : {len(bt_nonzero)} / {total_days}  ({pct(len(bt_nonzero), total_days)}%)")
print(f"  평균 백트래킹 횟수: {statistics.mean(bt_vals):.2f}")
print(f"  최대 백트래킹 횟수: {max(bt_vals)}")
max_bt_cases = sorted(entries, key=lambda x: -x["backtrack"])[:5]
print(f"\n  상위 5 백트래킹 day:")
for e in max_bt_cases:
    print(f"    번호={e['num']} {e['region']} {e['duration']} D{e['day']}  backtrack={e['backtrack']}")

# 8. 총 일정시간 분포
header("8. 총 일정시간 분포")
print(f"  평균  : {statistics.mean(dur_vals):.2f}h    중앙값: {statistics.median(dur_vals):.2f}h")
print(f"  P25   : {pctile(dur_vals,25):.2f}h    P75   : {pctile(dur_vals,75):.2f}h")
print(f"  최소  : {min(dur_vals):.2f}h    최대  : {max(dur_vals):.2f}h")
over_12h = [e for e in entries if e["total_hr"] >= 12.0]
print(f"  12h 초과 day: {len(over_12h)}건  (하루 12시간 이상 일정 — 비현실적)")
for e in sorted(over_12h, key=lambda x: -x["total_hr"])[:5]:
    print(f"    번호={e['num']} {e['region']} D{e['day']}  {e['total_hr']:.1f}h  "
          f"이동={e['travel_min']:.0f}분")

# 9. 종합 요약
header("9. AI 추천 성능 종합 요약")
total_valid = len(valid_route)

print(f"\n  [데이터 완결성]")
print(f"    경로 데이터 수집 실패율  : {pct(len(no_route), total_days)}% ({len(no_route)}/{total_days}일)")
print(f"    → Kakao API 일일 쿼터 초과로 항목 21~50 일부 누락")

print(f"\n  [이동 효율성]  (유효 {total_valid}일 기준)")
print(f"    정상 (travel_ratio < 20%) : {sum(1 for v in tr_vals if v < 0.20):2d}일 ({pct(sum(1 for v in tr_vals if v < 0.20), total_valid)}%)")
print(f"    경고 (20% ≤ ratio < 40%) : {sum(1 for v in tr_vals if 0.20 <= v < 0.40):2d}일 ({pct(sum(1 for v in tr_vals if 0.20 <= v < 0.40), total_valid)}%)")
print(f"    위험 (travel_ratio ≥ 40%) : {sum(1 for v in tr_vals if v >= 0.40):2d}일 ({pct(sum(1 for v in tr_vals if v >= 0.40), total_valid)}%)")

print(f"\n  [지리 일관성]")
print(f"    광역 이탈 (≥ 50km) : {len(dist_crit):2d}일 ({pct(len(dist_crit), total_days)}%)")
print(f"    → AI가 전혀 다른 도시의 장소를 같은 날 일정에 배치")

print(f"\n  [비현실 일정]")
print(f"    12h 초과 day : {len(over_12h)}건  (이동 시간이 포함된 실제 일정 기준)")
worst = max(valid_route, key=lambda x: x["travel_ratio"])
print(f"    최악 사례: 번호={worst['num']} {worst['region']} {worst['duration']} D{worst['day']}  "
      f"이동={worst['travel_min']:.0f}분 ({worst['travel_ratio']*100:.1f}%) / 총 {worst['total_hr']:.1f}h")

print(f"\n  [백트래킹]")
print(f"    백트래킹 발생률: {pct(len(bt_nonzero), total_days)}%  (비효율적 동선)")

print()
v    = len(valid_route)
warn = len(warn_days)
wp   = pct(warn, v)
print(f"{'='*60}")
print(f"  결론: 분석 가능한 {v}일 중 {warn}일({wp}%)의 일정에서")
print(f"  이동 비율이 20%를 초과. AI가 지리 최적화 없이")
print(f"  장소를 선택하는 구조적 한계를 수치로 확인.")
print(f"{'='*60}")
print()

# 결과 JSON 저장
report = {
    "summary": {
        "total_days": total_days,
        "valid_route_days": len(valid_route),
        "no_route_days": len(no_route),
        "geo_coverage_pct": pct(data["geo_coverage"]["hit"], data["geo_coverage"]["total"]),
    },
    "travel_ratio": {
        "mean": round(statistics.mean(tr_vals), 3),
        "median": round(statistics.median(tr_vals), 3),
        "stdev": round(statistics.stdev(tr_vals), 3),
        "cv": round(statistics.stdev(tr_vals) / statistics.mean(tr_vals), 3),
        "p25": round(pctile(tr_vals, 25), 3),
        "p75": round(pctile(tr_vals, 75), 3),
        "p90": round(pctile(tr_vals, 90), 3),
        "min": round(min(tr_vals), 3),
        "max": round(max(tr_vals), 3),
        "warn_n": len(warn_days),
        "warn_pct": pct(len(warn_days), total_valid),
        "crit_n": len(crit_days),
        "crit_pct": pct(len(crit_days), total_valid),
    },
    "by_duration": {
        dur: {
            "n": len(vals),
            "mean": round(statistics.mean(vals), 3),
            "median": round(statistics.median(vals), 3),
            "crit_n": sum(1 for v in vals if v >= TRAVEL_CRIT),
        }
        for dur, vals in by_dur.items() if vals
    },
    "geo_spread_crit_n": len(dist_crit),
    "backtrack_pct": pct(len(bt_nonzero), total_days),
    "over_12h_days": len(over_12h),
    "extreme_cases": [
        {
            "num": e["num"], "region": e["region"],
            "duration": e["duration"], "day": e["day"],
            "travel_ratio": e["travel_ratio"],
            "travel_min": e["travel_min"],
            "total_hr": e["total_hr"],
        }
        for e in extreme_cases
    ],
    "dist_crit_cases": [
        {
            "num": e["num"], "region": e["region"],
            "duration": e["duration"], "day": e["day"],
            "max_dist_km": e["max_dist_km"],
            "travel_ratio": e["travel_ratio"],
        }
        for e in long_dist_cases
    ],
}

out_path = BASE / "statistical_report.json"
out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"상세 보고서 저장 완료: {out_path}")
