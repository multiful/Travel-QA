<!-- updated: 2026-04-21 | hash: a426a576 | summary: Neo4j Cypher 쿼리 함수 (이동시간 합산, 구역 재방문, 운영시간 충돌) 구현 -->
# Step 2: graph-queries

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Cypher 쿼리 섹션)
- `/src/graph/schema.py`
- `/src/graph/neo4j_client.py`
- `/src/graph/queries.py` (phase 0 스텁)
- `/phases/3-graph/index.json` (step 1 summary 확인)

## 작업

`src/graph/queries.py`에 ARCHITECTURE.md에 정의된 Cypher 쿼리 함수들을 구현하고, `tests/test_graph_queries.py`를 작성하라.

### 1. `src/graph/queries.py` 구현

```python
from src.graph.neo4j_client import Neo4jClient

def get_total_travel_time(client: Neo4jClient, slot_ids: list[str]) -> float:
    """
    일정 내 TimeSlot 간 총 이동시간(분) 합계.
    반환: float (분)
    """
    query = """
    MATCH (t1:TimeSlot)-[r:TRAVELS_TO]->(t2:TimeSlot)
    WHERE t1.slot_id IN $slot_ids
    RETURN sum(r.travel_min) AS total_travel_min
    """
    ...

def get_area_revisits(client: Neo4jClient, poi_ids: list[str]) -> list[dict]:
    """
    동일 Area를 2회 이상 방문하는 경우 반환.
    반환: [{"area": "종로구", "visits": 2}, ...]
    """
    query = """
    MATCH (p:POI)-[:IN_AREA]->(a:Area)
    WHERE p.poi_id IN $poi_ids
    WITH a.name AS area, count(*) AS visits
    WHERE visits > 1
    RETURN area, visits ORDER BY visits DESC
    """
    ...

def get_operating_conflicts(client: Neo4jClient, poi_ids: list[str]) -> list[dict]:
    """
    운영시간 충돌 후보 (도착 예상이 운영 범위 밖인 POI).
    반환: [{"poi_name": "경복궁", "start_time": "08:30", "open_start": "09:00", "open_end": "18:00"}, ...]
    """
    query = """
    MATCH (p:POI)-[:SCHEDULED_AT]->(t:TimeSlot)
    WHERE p.poi_id IN $poi_ids
      AND (t.start_time < p.open_start OR t.start_time >= p.open_end)
    RETURN p.name AS poi_name, t.start_time, p.open_start, p.open_end
    """
    ...
```

### 2. `tests/test_graph_queries.py` 작성

`Neo4jClient.run`을 mock하여 테스트:

- `get_total_travel_time(client, slot_ids)` → `client.run()`이 slot_ids 파라미터로 호출 확인
- mock 반환 `[{"total_travel_min": 45.0}]` → `45.0` 반환 확인
- `get_area_revisits(client, poi_ids)` → visits > 1인 항목만 반환
- `get_operating_conflicts(client, poi_ids)` → poi_name, start_time 포함 확인
- 빈 결과 → 빈 리스트 반환 (None 반환 금지)

## Acceptance Criteria

```bash
python -m pytest tests/test_graph_queries.py -v
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/3-graph/index.json`의 step 2 status를 업데이트한다.

## 금지사항

- Cypher 파라미터를 문자열 포맷팅으로 삽입하지 마라 (`f"...{poi_id}..."` 금지). 반드시 `client.run(query, poi_ids=...)` 파라미터 바인딩 사용.
- 쿼리 결과가 없을 때 None을 반환하지 마라. 빈 리스트 또는 0.0을 반환한다.
