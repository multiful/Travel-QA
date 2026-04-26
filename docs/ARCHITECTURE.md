<!-- updated: 2026-04-21 | hash: d3289a74 | summary: 시스템 흐름, 디렉토리 구조, Neo4j 스키마, 점수 계산 공식, 오류 처리 -->
# 아키텍처

## 시스템 흐름

```
사용자 입력 (places + transport + travel_type + date)
    ↓
[API Layer] POST /validate
    ↓
[Explain Layer] ValidationOrchestrator.run(plan)
    ├── [Data]       TourAPIClient.get_poi(name)       → POI 메타데이터 (운영시간, 위치, 카테고리)
    ├── [Data]       KakaoClient.normalize_poi(name)   → 정규화된 POI 좌표 (Kakao Local API)
    ├── [Matrix]     TravelMatrixBuilder.build(pois)   → Pairwise 이동시간 행렬 (Kakao Mobility)
    ├── [Graph]      ItineraryGraphBuilder.build(plan) → Neo4j POI/Area/TimeSlot 저장
    ├── [Validation] HardFailDetector.detect(plan)     → Hard Fail 목록
    ├── [Validation] WarningDetector.detect(plan)      → Warning 목록
    ├── [Validation] ScoreCalculator.compute(plan)     → 5개 지표 점수
    └── [Explain]    ExplainEngine.explain(result)     → LLM 설명 + Repair 제안
    ↓
ValidationResult (Pydantic 모델)
```

## 디렉토리 구조

```
src/
├── data/
│   ├── models.py           # POI, ItineraryPlan, ValidationResult, Settings
│   ├── tour_api.py         # TourAPI v2 클라이언트 (async httpx)
│   └── kakao_client.py     # Kakao Local + Mobility API 클라이언트 (async httpx)
├── matrix/
│   └── travel_matrix.py    # Pairwise 이동시간·거리 행렬 빌더
├── graph/
│   ├── neo4j_client.py     # Neo4j 드라이버 컨텍스트 매니저
│   ├── schema.py           # 노드 라벨·관계 타입 상수
│   ├── builder.py          # ItineraryPlan → Neo4j 노드/엣지 upsert
│   └── queries.py          # Cypher 쿼리 함수 모음
├── validation/
│   ├── hard_fail.py        # Hard Fail 탐지 (운영시간 충돌, 이동 불가 등)
│   ├── warning.py          # Warning 탐지 (동선 비효율, 일정 과밀 등)
│   └── scoring.py          # 5개 지표 → Final Score
├── explain/
│   ├── prompts.py          # LLM 프롬프트 템플릿 (prompt caching 적용)
│   ├── explain_engine.py   # Claude API 호출 → Evidence-based 설명
│   └── orchestrator.py     # 전체 파이프라인 오케스트레이터
└── api/
    ├── main.py             # FastAPI app + lifespan
    ├── routes.py           # /validate, /repair/{plan_id}, /health
    └── schemas.py          # ValidateRequest, ValidateResponse Pydantic 스키마
tests/
├── test_data_models.py
├── test_tour_api.py
├── test_kakao_client.py
├── test_travel_matrix.py
├── test_neo4j_schema.py
├── test_graph_builder.py
├── test_graph_queries.py
├── test_hard_fail.py
├── test_warning.py
├── test_scoring.py
├── test_explain_engine.py
├── test_orchestrator.py
├── test_api_schemas.py
└── test_api_routes.py
```

## Neo4j 그래프 스키마

### 노드
| Label    | 필수 속성                                                          | 설명           |
|----------|--------------------------------------------------------------------|----------------|
| POI      | poi_id, name, lat, lng, category, open_start, open_end, duration_min | 방문 장소      |
| Area     | area_id, name                                                      | 지역 구역      |
| TimeSlot | slot_id, order, start_time, end_time                               | 방문 시간 슬롯 |

### 관계
| 관계         | 방향                   | 속성                              |
|--------------|------------------------|-----------------------------------|
| IN_AREA      | (POI)→(Area)           | (없음)                            |
| SCHEDULED_AT | (POI)→(TimeSlot)       | (없음)                            |
| FOLLOWED_BY  | (TimeSlot)→(TimeSlot)  | (없음)                            |
| TRAVELS_TO   | (TimeSlot)→(TimeSlot)  | travel_min, distance_km, mode     |

### 대표 Cypher 쿼리

```cypher
-- 일정 내 총 이동시간 합계
MATCH (t1:TimeSlot)-[r:TRAVELS_TO]->(t2:TimeSlot)
WHERE t1.slot_id IN $slot_ids
RETURN sum(r.travel_min) AS total_travel_min

-- 구역 재방문 탐지
MATCH (p:POI)-[:IN_AREA]->(a:Area)
WHERE p.poi_id IN $poi_ids
WITH a.name AS area, count(*) AS visits
WHERE visits > 1
RETURN area, visits ORDER BY visits DESC

-- Hard Fail 후보: 운영시간 충돌
MATCH (p:POI)-[:SCHEDULED_AT]->(t:TimeSlot)
WHERE p.poi_id IN $poi_ids
  AND (t.start_time < p.open_start OR t.start_time >= p.open_end)
RETURN p.name, t.start_time, p.open_start, p.open_end
```

## 데이터 흐름 (검증 파이프라인 상세)

```
1. TourAPI     → POI(name, lat, lng, category, open_start, open_end, usetime)
2. Kakao Local → 정규화된 좌표 (주소 기반 정제, 폴백: TourAPI 좌표 그대로 사용)
3. Kakao Mobility → TravelMatrix[i][j] = (travel_min, distance_km, mode)
   ※ Kakao Mobility 키 없음 → 직선거리 × 속도계수(transit:1.3, car:1.1, walk:1.0) 폴백
4. Graph: ItineraryGraphBuilder.build(plan, matrix) → Neo4j POI/Area/TimeSlot upsert
5. Validation (순수 Python, I/O 없음):
   hard_fails = HardFailDetector.detect(plan, matrix)
   warnings   = WarningDetector.detect(plan, matrix)
   scores     = ScoreCalculator.compute(plan, matrix)
6. Explain: ExplainEngine.explain(plan, hard_fails, warnings, scores)
   → ValidationResult(plan_id, final_score, hard_fails, warnings, scores, explanation, repair_suggestions)
```

## 점수 계산 공식

```
Efficiency    = baseline_heuristic_distance / actual_total_distance
              (baseline: nearest-neighbor heuristic)

Feasibility   = hard_feasibility × 0.5
              + temporal_feasibility × 0.3
              + human_feasibility × 0.2
              (hard: 0 if any Hard Fail, 1 otherwise)
              (temporal: 체류+이동 합계 / 가용 시간)
              (human: 1 - clamp(total_travel_km / 50, 0, 1))

PurposeFit    = 1 - cosine_distance(intent_vector, activity_vector)
              (intent_vector: travel_type별 기대 카테고리 분포)
              (activity_vector: POI 카테고리 실제 분포)

Flow          = 1 - (backtracking_ratio × 0.5
                   + revisit_area_ratio × 0.3
                   + cluster_switch_ratio × 0.2)

AreaIntensity = 1 - density_proxy
              (density_proxy: 동일 Area 내 POI 비율)

Final Score (0~100) =
    round((0.30 × Efficiency
         + 0.25 × Feasibility
         + 0.20 × PurposeFit
         + 0.15 × Flow
         + 0.10 × AreaIntensity) × 100)

Hard Fail 존재 시: Final Score = min(Final Score, 59)
```

## Confidence Level

| 항목          | 판정        | 신뢰도       |
|---------------|-------------|--------------|
| 운영시간 충돌  | Warning     | Medium       |
| 이동 불가      | Hard Fail   | High         |
| 체력 부담      | Warning     | Medium       |
| 목적 부적합    | Warning     | Medium-Low   |
| 시간적 수행 불가 | Hard Fail | High         |

## 설명 엔진 출력 구조 (4단계)

모든 판정은 아래 4단 구조로 LLM에게 생성하도록 지시한다:

1. **발견된 사실**: 경복궁 종료 10:50 / 인사동 도착 예상 11:30 / 운영 시작 09:00
2. **적용된 규칙**: 도착 예상 시간이 운영 시작 이후 → 정상 (충돌 없음)
3. **위험 판정**: 운영시간 충돌 없음. 단, 이동 35분으로 여유 시간 부족 (Medium confidence)
4. **개선 제안**: 경복궁 출발 시간 10분 앞당기기

## Repair 제안 우선순위

```
1순위: Hard Fail 제거 (운영시간 조정, 방문 순서 변경)
2순위: 구역 재방문 제거
3순위: 일정 과밀 완화 (장소 축소 또는 체류시간 조정)
4순위: 목적 적합성 개선
5순위: 이동 효율 개선
```

## 상태 관리
- Stateless API: 각 요청이 독립적으로 처리된다.
- 영속 저장: Neo4j에 일정 그래프 축적 (재검증 시 upsert로 덮어씀).
- `plan_id`: 장소명 목록 + 날짜의 SHA-256 앞 12자로 자동 생성.
- 설정: `pydantic-settings`로 `.env` → `Settings` 모델로 로드. 전역 싱글턴.

## 설정 관리

**Settings 주요 필드**
| 필드 | 기본값 | 설명 |
|------|--------|------|
| ANTHROPIC_API_KEY | (필수) | Claude API 인증 |
| CLAUDE_MODEL | "claude-sonnet-4-6" | LLM 모델명 |
| TOUR_API_KEY | (필수) | 한국관광공사 API 인증 |
| KAKAO_REST_API_KEY | (필수) | Kakao Local API 인증 |
| KAKAO_MOBILITY_KEY | "" | Kakao Mobility API (없으면 직선거리 폴백) |
| NEO4J_URI | "bolt://localhost:7687" | Neo4j 연결 |
| NEO4J_USER | "neo4j" | DB 사용자 |
| NEO4J_PASSWORD | (필수) | DB 비밀번호 |

## 오류 처리 전략

| 컴포넌트          | 실패 조건           | 처리 방식                   | 결과             |
|-----------------|-------------------|-----------------------------|----------------|
| TourAPI         | 관광지 없음          | `raise ValueError`          | API 404 반환    |
| TourAPI         | HTTP 5xx / 타임아웃 | 3회 재시도 후 `raise`        | API 503 반환    |
| Kakao Local     | POI 정규화 실패     | TourAPI 좌표 사용 (폴백)     | Warning 추가    |
| Kakao Mobility  | 키 없음 / 실패      | 직선거리 × 속도계수 폴백      | Confidence↓    |
| Neo4j 초기화    | 연결 실패           | `client = None`             | Graph 단계 skip |
| Claude API      | 타임아웃            | 3회 재시도 후 `raise`        | API 503 반환    |
| Validation      | 파싱 오류           | `raise` (즉시 노출)          | API 500 반환    |

Neo4j가 None이면 Graph 저장 skip, Validation/Explain은 정상 진행.

## 성능 고려사항

| 항목                   | 예상 시간              | 최적화 방법                                   |
|----------------------|----------------------|---------------------------------------------|
| TourAPI (POI당)       | ~0.5-1s              | 일정 내 POI asyncio.gather로 병렬 호출         |
| Kakao Mobility 행렬   | ~1-3s (N×N, N≤8)     | 순차 호출로 충분 (최대 56 쌍)                  |
| Neo4j upsert         | ~10-50ms/query       | 드라이버 연결 풀 자동 관리                      |
| Validation Engine    | ~50-200ms            | 순수 Python 계산 (I/O 없음)                   |
| Claude API 호출      | ~3-8s                | SYSTEM_PROMPT 캐싱으로 토큰 비용 ~60% 절감    |
| 전체 /validate        | ~8-15s (cold) / ~5-8s (warm) | 2회차 이후 TourAPI 응답 Neo4j 캐시 활용 |
