"""
트리플 앱 추천 경로 분석 파이프라인 (대한민국 노선만)
구석구석 analyze.py와 동일 지표를 산출하여 비교 기반 데이터 생성
"""
import json, os, re, time, requests, statistics, math, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KR_LAT = (33.0, 38.7)
KR_LON = (124.5, 132.0)

def _load_env():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

KAKAO_KEY      = os.environ.get("KAKAO_MOBILITY_KEY", "")
KAKAO_REST_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
TOUR_KEY       = os.environ.get("TOUR_API_KEY", "")
if not KAKAO_KEY or not TOUR_KEY:
    raise RuntimeError("KAKAO_MOBILITY_KEY / TOUR_API_KEY 환경변수가 설정되지 않았습니다.")

BASE        = Path(__file__).resolve().parent
CACHE_GEO   = BASE / "cache_geo.json"
CACHE_ROUTE = BASE / "cache_route.json"
OUT_FILE    = BASE / "triple_analysis_result.json"
EXCEL_FILE  = BASE / "트리플 여행 추천 경로.xlsx"

DWELL = {"attraction": 90 * 60, "food": 60 * 60}

# ── 0. 캐시 로드 & 오염 정화 ─────────────────────────────────────────────
try:
    route_cache = json.load(open(CACHE_ROUTE, encoding="utf-8"))
    null_count = sum(1 for v in route_cache.values() if v is None)
    if null_count:
        route_cache = {k: v for k, v in route_cache.items() if v is not None}
        CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")
        print(f"[route캐시 정화] None {null_count}개 제거")
except FileNotFoundError:
    route_cache = {}

try:
    geo_cache = json.load(open(CACHE_GEO, encoding="utf-8"))
    for k, v in list(geo_cache.items()):
        if v is not None:
            lat, lon = v
            if not (KR_LAT[0] <= lat <= KR_LAT[1] and KR_LON[0] <= lon <= KR_LON[1]):
                geo_cache[k] = None
except FileNotFoundError:
    geo_cache = {}

# ── 1. Excel 파싱 ─────────────────────────────────────────────────────────
import openpyxl

wb  = openpyxl.load_workbook(EXCEL_FILE)
ws  = wb.active
raw = list(ws.iter_rows(values_only=True))

# 헤더 행(index 10, 0-based)부터 데이터 시작
DATA_START = 11  # 0-based index = row 12 (1-based)

def parse_numbered(cell_str):
    """'1.장소A, 3.장소B' → {1: '장소A', 3: '장소B'}"""
    if not cell_str:
        return {}
    result = {}
    # "N.이름" 또는 "N. 이름" 패턴
    parts = re.split(r",\s*(?=\d+[.\s])", str(cell_str))
    for part in parts:
        part = part.strip()
        m = re.match(r"^(\d+)[.\s]\s*(.+)", part)
        if m:
            num  = int(m.group(1))
            name = m.group(2).strip()
            name = re.sub(r"\s*\[.*?\]", "", name).strip()
            name = re.sub(r"\(구\s+.+?\)", "", name).strip()
            if name:
                result[num] = name
    return result

entries = []
i = DATA_START
while i < len(raw):
    row = raw[i]
    num_raw = row[0]
    if num_raw is None or str(num_raw).strip() == "":
        i += 1
        continue

    # "3 (2번 재추천 항목)" 같은 형식 → 숫자만 추출
    num_str = re.match(r"^\s*(\d+)", str(num_raw))
    if not num_str:
        i += 1
        continue

    country = row[1]
    if country != "대한민국":
        i += 1
        continue

    num      = int(num_str.group(1))
    city     = str(row[2]).strip() if row[2] else ""
    duration = str(row[3]).strip() if row[3] else ""
    companion= str(row[4]).strip() if row[4] else ""
    style    = str(row[5]).strip() if row[5] else ""

    # 지역(장소), 음식, 숙소 행 수집
    place_row = food_row = None
    j = i
    while j < len(raw) and j < i + 5:
        r = raw[j]
        cat = str(r[7]).strip() if r[7] is not None else ""
        if "지역" in cat:
            place_row = r
        elif "음식" in cat:
            food_row = r
        elif "숙소" in cat:
            pass  # 숙소는 지표 계산에서 제외
        j += 1

    # DAY 컬럼: index 8~13 → DAY1~DAY6
    days = []
    for d in range(6):
        col = 8 + d
        places_raw = place_row[col] if place_row and col < len(place_row) else None
        foods_raw  = food_row[col]  if food_row  and col < len(food_row)  else None

        p_dict = parse_numbered(places_raw)
        f_dict = parse_numbered(foods_raw)

        merged = {}
        for n, nm in p_dict.items():
            merged[n] = {"name": nm, "type": "attraction"}
        for n, nm in f_dict.items():
            merged[n] = {"name": nm, "type": "food"}

        if merged:
            seq = [merged[k] for k in sorted(merged)]
            days.append(seq)

    if days:
        entries.append({
            "num": num, "city": city, "duration": duration,
            "companion": companion, "style": style, "days": days,
        })
    i += 1

print(f"[파싱] 대한민국 {len(entries)}개 항목")

# ── 2. 지오코딩 ───────────────────────────────────────────────────────────
_nominatim_lock = threading.Lock()

def geocode_tourapi(name):
    try:
        r = requests.get(
            "http://apis.data.go.kr/B551011/KorService2/searchKeyword2",
            params={"serviceKey": TOUR_KEY, "keyword": name,
                    "MobileOS": "ETC", "MobileApp": "TravelAnalyzer",
                    "numOfRows": 1, "_type": "json"},
            timeout=5
        )
        if r.status_code == 200:
            body = r.json()["response"]["body"]
            items = body.get("items")
            if items and items != "":
                item = items["item"]
                if isinstance(item, list):
                    item = item[0]
                lat, lon = float(item["mapy"]), float(item["mapx"])
                if KR_LAT[0] <= lat <= KR_LAT[1] and KR_LON[0] <= lon <= KR_LON[1]:
                    return lat, lon
    except Exception:
        pass
    return None

def geocode_kakao_local(name, city=""):
    """Kakao Local API — 현지 카페·식당·관광지까지 광범위하게 커버.
    city는 언더스코어 형식('가평_양평')이므로 쿼리에 포함하지 않음."""
    if not KAKAO_REST_KEY:
        return None
    query = name  # Kakao 검색엔진은 이름만으로 충분, city 포함 시 언더스코어로 오히려 실패
    try:
        r = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
            params={"query": query, "size": 1},
            timeout=5
        )
        if r.status_code == 200:
            docs = r.json().get("documents", [])
            if docs:
                lat = float(docs[0]["y"])
                lon = float(docs[0]["x"])
                if KR_LAT[0] <= lat <= KR_LAT[1] and KR_LON[0] <= lon <= KR_LON[1]:
                    return lat, lon
    except Exception:
        pass
    return None

def geocode_nominatim(name, city=""):
    query = f"{name} {city} 대한민국".strip()
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "countrycodes": "kr",
                    "format": "json", "limit": 1},
            headers={"User-Agent": "TravelValidator/1.0"},
            timeout=5
        )
        if r.status_code == 200 and r.json():
            d = r.json()[0]
            return float(d["lat"]), float(d["lon"])
    except Exception:
        pass
    return None

def geocode_single(args):
    """TourAPI → Kakao Local → Nominatim 순으로 시도 (병렬 호출 안전)"""
    nm, city = args
    coord = geocode_tourapi(nm)
    if coord is None:
        coord = geocode_kakao_local(nm, city)
    if coord is None:
        with _nominatim_lock:  # Nominatim은 1req/sec 직렬화
            time.sleep(1.1)
            coord = geocode_nominatim(nm, city)
    return nm, coord

all_pois = {}
for e in entries:
    for day in e["days"]:
        for poi in day:
            nm = poi["name"]
            if nm not in all_pois:
                all_pois[nm] = (e["city"], poi["type"])

# geo_cache에서 현재 None인 항목 중 all_pois에 속하는 것만 재시도
retry_geo = {nm for nm in all_pois if geo_cache.get(nm) is None}
new_geo   = {nm for nm in all_pois if nm not in geo_cache}
need_geo  = list(retry_geo | new_geo)
print(f"[지오코딩] 총 {len(all_pois)}개 장소, 재시도 {len(retry_geo)}개 + 신규 {len(new_geo)}개 = {len(need_geo)}개")

if need_geo:
    done = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        for nm, coord in executor.map(geocode_single, [(nm, all_pois[nm][0]) for nm in need_geo]):
            geo_cache[nm] = coord
            done += 1
            if done % 20 == 0:
                CACHE_GEO.write_text(json.dumps(geo_cache, ensure_ascii=False), encoding="utf-8")
                print(f"  {done}/{len(need_geo)} 처리 중...")

CACHE_GEO.write_text(json.dumps(geo_cache, ensure_ascii=False), encoding="utf-8")
hit  = sum(1 for nm in all_pois if geo_cache.get(nm))
miss = sum(1 for nm in all_pois if not geo_cache.get(nm))
print(f"[지오코딩 완료] Triple 장소 성공 {hit}/{len(all_pois)}, 실패 {miss}")

# ── 3. 이동시간 계산 ──────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def haversine_travel_sec(lat1, lon1, lat2, lon2, speed_kmh=20.0, detour=1.3):
    dist_m = haversine(lat1, lon1, lat2, lon2)
    return int(dist_m * detour / (speed_kmh * 1000 / 3600))

_quota_exhausted = False

def get_travel_time(lat1, lon1, lat2, lon2):
    global _quota_exhausted
    key = f"{lon1:.4f},{lat1:.4f}|{lon2:.4f},{lat2:.4f}"
    cached = route_cache.get(key, "MISSING")
    if cached != "MISSING" and cached is not None:
        return cached
    if not _quota_exhausted:
        try:
            r = requests.get(
                "https://apis-navi.kakaomobility.com/v1/directions",
                headers={"Authorization": f"KakaoAK {KAKAO_KEY}"},
                params={"origin": f"{lon1},{lat1}", "destination": f"{lon2},{lat2}"},
                timeout=5
            )
            if r.status_code == 429:
                _quota_exhausted = True
                print("[Kakao] 일일 쿼터 소진 — 이후 haversine 전환")
            elif r.status_code == 200:
                routes = r.json().get("routes", [])
                if routes and routes[0].get("sections"):
                    val = routes[0]["sections"][0]["duration"]
                    route_cache[key] = val
                    CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")
                    return val
        except Exception:
            pass
    return haversine_travel_sec(lat1, lon1, lat2, lon2)

# ── 4. 지표 계산 ──────────────────────────────────────────────────────────
def cluster_label(lat, lon):
    return (round(lat * 20) / 20, round(lon * 20) / 20)

results = []
route_calls = 0

for e in entries:
    days_metrics = []
    for day_seq in e["days"]:
        travel_sec = 0
        dwell_sec  = 0
        coords     = []
        clusters   = []
        prev_cluster = None
        backtrack_count = 0

        for poi in day_seq:
            coord = geo_cache.get(poi["name"])
            dwell_sec += DWELL[poi["type"]]
            if coord:
                lat, lon = coord
                coords.append((lat, lon))
                cl = cluster_label(lat, lon)
                if prev_cluster is not None and cl == prev_cluster and cl in clusters[:-1]:
                    backtrack_count += 1
                clusters.append(cl)
                prev_cluster = cl

        route_ok = route_est = 0
        for idx in range(len(coords) - 1):
            lat1, lon1 = coords[idx]
            lat2, lon2 = coords[idx + 1]
            key = f"{lon1:.4f},{lat1:.4f}|{lon2:.4f},{lat2:.4f}"
            kakao_val = route_cache.get(key)
            t = get_travel_time(lat1, lon1, lat2, lon2)
            route_calls += 1
            travel_sec += t
            if kakao_val is not None:
                route_ok += 1
            else:
                route_est += 1
            time.sleep(0.05)

        total_sec = travel_sec + dwell_sec
        # geo_hit<2이면 이동구간 없어 travel_ratio 산출 불가 → None 처리
        if len(coords) >= 2 and total_sec > 0:
            travel_ratio = travel_sec / total_sec
        else:
            travel_ratio = None

        max_dist_km = 0
        for ci in range(len(coords)):
            for cj in range(ci + 1, len(coords)):
                d = haversine(*coords[ci], *coords[cj]) / 1000
                max_dist_km = max(max_dist_km, d)

        region_switches = sum(1 for a, b in zip(clusters, clusters[1:]) if a != b)

        days_metrics.append({
            "poi_count":       len(day_seq),
            "geo_hit":         len(coords),
            "travel_sec":      travel_sec,
            "dwell_sec":       dwell_sec,
            "total_sec":       total_sec,
            "travel_ratio":    round(travel_ratio, 3) if travel_ratio is not None else None,
            "travel_min":      round(travel_sec / 60, 1),
            "total_hr":        round(total_sec / 3600, 2),
            "backtrack":       backtrack_count,
            "max_dist_km":     round(max_dist_km, 2),
            "region_switches": region_switches,
            "route_coverage":  f"{route_ok}/{max(len(coords)-1, 1)}",
            "route_estimated": route_est,
        })

    results.append({**e, "days": None, "metrics": days_metrics})

CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")
print(f"[경로 계산] 총 {route_calls}회 API 호출")

# ── 5. 통계 집계 ─────────────────────────────────────────────────────────
def percentile(data, p):
    data = sorted(data)
    idx = (len(data) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (idx - lo)

def stats_block(data):
    if not data:
        return {"n": 0}
    return {
        "n":      len(data),
        "mean":   round(statistics.mean(data), 3),
        "median": round(statistics.median(data), 3),
        "stdev":  round(statistics.stdev(data), 3) if len(data) > 1 else 0,
        "p25":    round(percentile(data, 25), 3),
        "p75":    round(percentile(data, 75), 3),
        "p90":    round(percentile(data, 90), 3),
        "min":    round(min(data), 3),
        "max":    round(max(data), 3),
    }

all_tr, all_dur, all_dist = [], [], []
dur_group = {"당일치기": [], "1박 2일": [], "2박 3일": [], "3박 이상": []}
city_group = {}
companion_group = {}

entry_summary = []
for r in results:
    dur_key = r["duration"]
    if "당일" in dur_key:
        norm = "당일치기"
    elif "1박" in dur_key:
        norm = "1박 2일"
    elif "2박" in dur_key:
        norm = "2박 3일"
    else:
        norm = "3박 이상"

    city = r["city"]
    comp = r["companion"]
    if city not in city_group:
        city_group[city] = []
    if comp not in companion_group:
        companion_group[comp] = []

    for di, m in enumerate(r["metrics"]):
        if m["travel_ratio"] is not None:
            all_tr.append(m["travel_ratio"])
            dur_group[norm].append(m["travel_ratio"])
            city_group[city].append(m["travel_ratio"])
            companion_group[comp].append(m["travel_ratio"])
        if m["total_sec"] > 0:
            all_dur.append(m["total_hr"])
        if m["max_dist_km"] > 0:
            all_dist.append(m["max_dist_km"])

        entry_summary.append({
            "num": r["num"], "city": city, "duration": norm,
            "companion": comp, "day": di + 1, **m
        })

warn_n = sum(1 for v in all_tr if 0.20 <= v < 0.40)
crit_n = sum(1 for v in all_tr if v >= 0.40)
norm_n = len(all_tr) - warn_n - crit_n

over_12h = sum(1 for v in all_dur if v > 12)
backtrack_days = sum(1 for e in entry_summary if e["backtrack"] > 0)
geo_spread_crit = sum(1 for e in entry_summary if e["max_dist_km"] > 50)

output = {
    "source": "triple",
    "summary": {
        "total_entries": len(entries),
        "total_days":    len(entry_summary),
        "cities":        list(city_group.keys()),
        "geo_coverage_pct": round(hit / max(hit + miss, 1) * 100, 1),
    },
    "travel_ratio": {
        "전체":     stats_block(all_tr),
        "당일치기": stats_block(dur_group["당일치기"]),
        "1박 2일":  stats_block(dur_group["1박 2일"]),
        "2박 3일":  stats_block(dur_group["2박 3일"]),
        "3박 이상": stats_block(dur_group["3박 이상"]),
        "warn_n":   warn_n,
        "crit_n":   crit_n,
        "norm_n":   norm_n,
        "warn_pct": round(warn_n / max(len(all_tr), 1) * 100, 1),
        "crit_pct": round(crit_n / max(len(all_tr), 1) * 100, 1),
    },
    "total_duration_hr": stats_block(all_dur),
    "max_dist_km":       stats_block(all_dist),
    "over_12h_days":     over_12h,
    "backtrack_days":    backtrack_days,
    "backtrack_pct":     round(backtrack_days / max(len(entry_summary), 1) * 100, 1),
    "geo_spread_crit_n": geo_spread_crit,
    "by_city":           {k: stats_block(v) for k, v in city_group.items() if v},
    "entries":           entry_summary,
}

OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n========== Triple 분석 결과 ==========")
s = output["travel_ratio"]["전체"]
print(f"Travel Ratio: 평균={s.get('mean','N/A')}, 중앙={s.get('median','N/A')}, n={s.get('n',0)}")
print(f"  정상 {norm_n}건, 경고 {warn_n}건, 위험 {crit_n}건")
print(f"12시간 초과: {over_12h}일 / 백트래킹: {backtrack_days}일 ({output['backtrack_pct']}%)")
print(f"\n결과 저장: {OUT_FILE}")
