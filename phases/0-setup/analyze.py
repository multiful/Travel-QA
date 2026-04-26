"""
구석구석 50개 여행 경로 분석 파이프라인
1. 장소명 파싱 → 2. 지오코딩 → 3. 이동시간 계산 → 4. 지표 산출 → 5. 통계 출력
"""
import json, os, re, time, requests, statistics, math, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import defaultdict

# 한국 좌표 경계 (대략)
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

BASE       = Path(__file__).resolve().parent
CACHE_GEO  = BASE / "cache_geo.json"
CACHE_ROUTE= BASE / "cache_route.json"
OUT_FILE   = BASE / "analysis_result.json"

DWELL = {"attraction": 90*60, "food": 60*60}  # 초 단위

# ── 0. 데이터 로드 ─────────────────────────────────────────────────────
with open(BASE / "gg2.json", encoding="utf-8") as f:
    rows = json.load(f)

# ── 1. 파싱 ───────────────────────────────────────────────────────────
def parse_cell(cell):
    """'1.장소A, 3.장소B, 2.음식C' → {1: '장소A', 2: '음식C', 3: '장소B'}"""
    if not cell:
        return {}
    result = {}
    # 번호+점으로 시작하는 위치에서 분리
    parts = re.split(r",\s*(?=\d+[.\s])", cell)
    for part in parts:
        part = part.strip()
        m = re.match(r"^(\d+)[.\s]\s*(.+)", part)
        if m:
            num  = int(m.group(1))
            name = m.group(2).strip()
            name = re.sub(r"\s*\[.*?\]", "", name).strip()   # [...] 제거
            name = re.sub(r"\(구\s+.+?\)", "", name).strip()  # (구 ...) 제거
            if name:
                result[num] = name
    return result

entries = []
i = 4
while i < len(rows):
    row = rows[i]
    if row[0] is not None and str(row[0]).strip() and i + 2 < len(rows):
        food_row  = rows[i + 1]
        entry = {
            "num":      row[0],
            "region":   row[1],
            "duration": str(row[3]).strip(),
            "theme":    str(row[4]).strip() if row[4] else "",
            "days":     [],
        }
        for d in range(3):
            col     = 6 + d
            places  = parse_cell(row[col])
            foods   = parse_cell(food_row[col])
            merged  = {}
            for n, nm in places.items():
                merged[n] = {"name": nm, "type": "attraction"}
            for n, nm in foods.items():
                merged[n] = {"name": nm, "type": "food"}
            if merged:
                seq = [merged[k] for k in sorted(merged)]
                entry["days"].append(seq)
        entries.append(entry)
    i += 1

print(f"[파싱] {len(entries)}개 항목")

# ── 2. 지오코딩 ───────────────────────────────────────────────────────
try:
    geo_cache = json.load(open(CACHE_GEO, encoding="utf-8"))
    # 잘못된 좌표(0,0 또는 한국 경계 밖) 제거
    for k, v in list(geo_cache.items()):
        if v is not None:
            lat, lon = v
            if not (KR_LAT[0] <= lat <= KR_LAT[1] and KR_LON[0] <= lon <= KR_LON[1]):
                geo_cache[k] = None
except FileNotFoundError:
    geo_cache = {}

_nominatim_lock = threading.Lock()

def geocode_tourapi(name, region=""):
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

def geocode_kakao_local(name, region=""):
    """Kakao Local API — 현지 카페·식당·관광지까지 광범위하게 커버.
    region은 언더스코어 형식 가능성이 있어 쿼리에 포함하지 않음."""
    if not KAKAO_REST_KEY:
        return None
    query = name  # Kakao 검색엔진은 이름만으로 충분
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

def geocode_nominatim(name, region=""):
    query = f"{name} {region} 대한민국".strip()
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
    """TourAPI → Kakao Local → Nominatim 순 (병렬 호출 안전)"""
    nm, region = args
    coord = geocode_tourapi(nm, region)
    if coord is None:
        coord = geocode_kakao_local(nm, region)
    if coord is None:
        with _nominatim_lock:
            time.sleep(1.1)
            coord = geocode_nominatim(nm, region)
    return nm, coord

# 모든 unique 장소 수집
all_pois = {}  # name → (region, type)
for e in entries:
    for day in e["days"]:
        for poi in day:
            nm = poi["name"]
            if nm not in all_pois:
                all_pois[nm] = (e["region"], poi["type"])

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
print(f"[지오코딩 완료] 성공 {hit}, 실패 {miss}")

# ── 3. 이동시간 계산 (Kakao Mobility) ────────────────────────────────
try:
    route_cache = json.load(open(CACHE_ROUTE, encoding="utf-8"))
except FileNotFoundError:
    route_cache = {}

def haversine_travel_sec(lat1, lon1, lat2, lon2, speed_kmh=20.0, detour=1.3):
    """직선거리 × 우회계수 / 속도 로 이동 시간(초) 추정. Kakao API 불가 시 폴백."""
    dist_m = haversine(lat1, lon1, lat2, lon2)
    return int(dist_m * detour / (speed_kmh * 1000 / 3600))

_quota_exhausted = False  # 한 번 429 받으면 이번 실행 동안 API 호출 중단

def get_travel_time(lat1, lon1, lat2, lon2):
    global _quota_exhausted
    key = f"{lon1:.4f},{lat1:.4f}|{lon2:.4f},{lat2:.4f}"
    cached = route_cache.get(key, "MISSING")
    if cached != "MISSING" and cached is not None:
        return cached  # 캐시된 실측값 사용
    # 캐시에 없거나 None(이전 오염) → API 재시도 (단, 쿼터 소진 시 haversine)
    if not _quota_exhausted:
        try:
            r = requests.get(
                "https://apis-navi.kakaomobility.com/v1/directions",
                headers={"Authorization": f"KakaoAK {KAKAO_KEY}"},
                params={"origin":      f"{lon1},{lat1}",
                        "destination": f"{lon2},{lat2}"},
                timeout=5
            )
            if r.status_code == 429:
                _quota_exhausted = True
                print("[Kakao] 일일 쿼터 소진 — 이후 haversine 추정으로 전환")
            elif r.status_code == 200:
                routes = r.json().get("routes", [])
                if routes and routes[0].get("sections"):
                    val = routes[0]["sections"][0]["duration"]
                    route_cache[key] = val
                    # 즉시 저장(오염 방지)
                    CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")
                    return val
        except Exception:
            pass
    # 실패(쿼터·타임아웃)는 캐시에 기록하지 않고 haversine으로 추정
    return haversine_travel_sec(lat1, lon1, lat2, lon2)

# ── 4. 지표 계산 ──────────────────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def cluster_label(lat, lon, radius_km=5):
    """단순 그리드 기반 지역 클러스터 레이블 (5km 격자)"""
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

        # 이동시간 계산 (Kakao API 실측 우선, 실패 시 haversine 추정)
        route_ok = 0
        route_est = 0
        for idx in range(len(coords) - 1):
            lat1, lon1 = coords[idx]
            lat2, lon2 = coords[idx + 1]
            key = f"{lon2:.4f},{lat2:.4f}|{lon1:.4f},{lat1:.4f}"  # direction check
            kakao_val = route_cache.get(f"{lon1:.4f},{lat1:.4f}|{lon2:.4f},{lat2:.4f}")
            t = get_travel_time(lat1, lon1, lat2, lon2)
            route_calls += 1
            travel_sec += t
            if kakao_val is not None:
                route_ok += 1
            else:
                route_est += 1
            time.sleep(0.05)

        total_sec = travel_sec + dwell_sec
        travel_ratio = travel_sec / total_sec if total_sec > 0 else None

        # 공간 응집도: 최대 직선거리 (km)
        max_dist_km = 0
        for ci in range(len(coords)):
            for cj in range(ci+1, len(coords)):
                d = haversine(*coords[ci], *coords[cj]) / 1000
                max_dist_km = max(max_dist_km, d)

        # 지역 전환 수
        region_switches = sum(1 for a, b in zip(clusters, clusters[1:]) if a != b)

        days_metrics.append({
            "poi_count":      len(day_seq),
            "geo_hit":        len(coords),
            "travel_sec":     travel_sec,
            "dwell_sec":      dwell_sec,
            "total_sec":      total_sec,
            "travel_ratio":   round(travel_ratio, 3) if travel_ratio is not None else None,
            "travel_min":     round(travel_sec / 60, 1),
            "total_hr":       round(total_sec / 3600, 2),
            "backtrack":      backtrack_count,
            "max_dist_km":    round(max_dist_km, 2),
            "region_switches":region_switches,
            "route_coverage": f"{route_ok}/{max(len(coords)-1,1)}",
            "route_estimated": route_est,
        })

        if route_calls % 50 == 0:
            CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")

    results.append({**e, "days": None, "metrics": days_metrics})

CACHE_ROUTE.write_text(json.dumps(route_cache), encoding="utf-8")

print(f"[경로 계산] 총 {route_calls}회 API 호출")

# ── 5. 통계 집계 ─────────────────────────────────────────────────────
def percentile(data, p):
    data = sorted(data)
    idx = (len(data) - 1) * p / 100
    lo, hi = int(idx), min(int(idx) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (idx - lo)

all_tr, all_dur, all_dist = [], [], []
dur_group = {"당일여행": [], "1박 2일": [], "2박 3일": []}

for r in results:
    dur_key = r["duration"]
    norm_dur = "당일여행" if "당일" in dur_key else ("1박 2일" if "1박" in dur_key else "2박 3일")
    for m in r["metrics"]:
        if m["travel_ratio"] is not None:
            all_tr.append(m["travel_ratio"])
            dur_group[norm_dur].append(m["travel_ratio"])
        if m["total_sec"] > 0:
            all_dur.append(m["total_hr"])
        if m["max_dist_km"] > 0:
            all_dist.append(m["max_dist_km"])

def stats_block(data, label):
    if not data:
        return {label: "데이터 없음"}
    return {
        "n": len(data),
        "mean": round(statistics.mean(data), 3),
        "median": round(statistics.median(data), 3),
        "stdev": round(statistics.stdev(data), 3) if len(data) > 1 else 0,
        "p25": round(percentile(data, 25), 3),
        "p75": round(percentile(data, 75), 3),
        "p90": round(percentile(data, 90), 3),
        "min": round(min(data), 3),
        "max": round(max(data), 3),
    }

# 항목별 상세 결과
entry_summary = []
for r in results:
    for di, m in enumerate(r["metrics"]):
        dur_key = r["duration"]
        norm_dur = "당일여행" if "당일" in dur_key else ("1박 2일" if "1박" in dur_key else "2박 3일")
        entry_summary.append({
            "num": r["num"], "region": r["region"],
            "duration": norm_dur, "day": di+1,
            **m
        })

output = {
    "travel_ratio": {
        "전체": stats_block(all_tr, "전체"),
        "당일여행": stats_block(dur_group["당일여행"], "당일여행"),
        "1박 2일": stats_block(dur_group["1박 2일"], "1박 2일"),
        "2박 3일": stats_block(dur_group["2박 3일"], "2박 3일"),
    },
    "total_duration_hr": stats_block(all_dur, "전체"),
    "max_dist_km": stats_block(all_dist, "전체"),
    "geo_coverage": {"hit": hit, "miss": miss, "total": hit + miss},
    "entries": entry_summary,
}

OUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

# 콘솔 출력
print("\n========== 분석 결과 ==========")
print("\n[Travel Ratio 분포]")
for k, v in output["travel_ratio"].items():
    if isinstance(v, dict) and "mean" in v:
        print(f"  {k}: 평균={v['mean']}, 중앙={v['median']}, P25={v['p25']}, P75={v['p75']}, n={v['n']}")

print("\n[총 일정시간 (시간)]")
d = output["total_duration_hr"]
if "mean" in d:
    print(f"  평균={d['mean']}h, 중앙={d['median']}h, P25={d['p25']}h, P75={d['p75']}h, n={d['n']}")

print("\n[최대 직선거리 (km)]")
d = output["max_dist_km"]
if "mean" in d:
    print(f"  평균={d['mean']}km, 중앙={d['median']}km, P75={d['p75']}km, n={d['n']}")

print(f"\n결과 저장: {OUT_FILE}")
print("분석 완료")
