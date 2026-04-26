<!-- updated: 2026-04-21 | hash: c1e4cf7c | summary: ItineraryPlan → Neo4j POI/Area/TimeSlot 그래프 빌더 구현 -->
# Step 1: graph-builder

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Neo4j 스키마, Cypher 쿼리)
- `/src/data/models.py`
- `/src/graph/schema.py`
- `/src/graph/neo4j_client.py`
- `/src/graph/builder.py` (phase 0 스텁)
- `/phases/3-graph/index.json` (step 0 summary 확인)

## 작업

`src/graph/builder.py`에 여행 일정을 Neo4j 그래프로 저장하는 빌더를 구현하고, `tests/test_graph_builder.py`를 작성하라.

### 1. `src/graph/builder.py` 구현

```python
import hashlib
from src.data.models import POI, ItineraryPlan
from src.graph.neo4j_client import Neo4jClient
from src.graph.schema import NodeLabel, RelType

class ItineraryGraphBuilder:
    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    def build(self, plan: ItineraryPlan, pois: list[POI], matrix: dict) -> None:
        """
        ItineraryPlan + POI 목록 + 이동시간 행렬을 받아 Neo4j에 저장.
        순서: POI upsert → Area upsert → TimeSlot upsert → 관계 생성
        """
        sorted_places = sorted(plan.places, key=lambda p: p.visit_order)
        for i, (place, poi) in enumerate(zip(sorted_places, pois)):
            self._upsert_poi(poi)
            self._upsert_area(poi)
            slot = self._upsert_time_slot(plan, i, place, poi)
            if i > 0:
                prev_slot = self._make_slot_id(plan.plan_id, i - 1)
                self._create_followed_by(prev_slot, slot)
                travel = matrix[i - 1][i]
                self._create_travels_to(prev_slot, slot, travel)

    def _upsert_poi(self, poi: POI) -> None:
        # POI 노드 MERGE (poi_id 기준)
        ...

    def _upsert_area(self, poi: POI) -> None:
        # Area 노드 MERGE + (POI)-[:IN_AREA]->(Area) 생성
        # Area name은 poi.category 또는 행정구역 (MVP: poi.category 사용)
        ...

    def _upsert_time_slot(self, plan: ItineraryPlan, order: int, place, poi: POI) -> str:
        # TimeSlot 노드 MERGE + (POI)-[:SCHEDULED_AT]->(TimeSlot)
        # start_time/end_time 계산 (plan.start_time + 이전 이동시간 + 체류시간 누적)
        # slot_id 반환
        ...

    def _make_slot_id(self, plan_id: str, order: int) -> str:
        return f"{plan_id}_slot_{order}"

    def _create_followed_by(self, slot1_id: str, slot2_id: str) -> None:
        # (TimeSlot {slot_id: slot1_id})-[:FOLLOWED_BY]->(TimeSlot {slot_id: slot2_id})
        ...

    def _create_travels_to(self, slot1_id: str, slot2_id: str, travel: dict) -> None:
        # (TimeSlot)-[:TRAVELS_TO {travel_min, distance_km, mode}]->(TimeSlot)
        ...
```

### 2. `tests/test_graph_builder.py` 작성

`Neo4jClient.run`을 mock으로 대체:

- `build(plan, pois, matrix)` → `client.run()`이 최소 POI수×3회 이상 호출 확인
- `_upsert_poi(poi)` → MERGE 쿼리에 `poi_id` 파라미터 포함 확인
- `_create_travels_to(...)` → `TRAVELS_TO` 관계 속성 (travel_min, distance_km) 전달 확인
- 빈 places 목록 → run 호출 없음

## Acceptance Criteria

```bash
python -m pytest tests/test_graph_builder.py -v
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/3-graph/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- 모든 쿼리에서 `MERGE`를 사용하라. `CREATE`는 중복 노드를 생성하므로 금지.
- `TRAVELS_TO` 관계는 방향이 있다: (앞 TimeSlot)→(뒤 TimeSlot). 반대 방향 금지.
- 테스트에서 실제 Neo4j 연결을 시도하지 마라.
