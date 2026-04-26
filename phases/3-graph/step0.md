<!-- updated: 2026-04-21 | hash: bf3ff7fc | summary: Neo4j 스키마 상수·제약조건 + 클라이언트 구현 (POI/Area/TimeSlot) -->
# Step 0: neo4j-schema

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 기획·아키텍처·설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md` (Neo4j 그래프 스키마 섹션)
- `/src/data/models.py`
- `/src/graph/schema.py` (phase 0 스텁)
- `/src/graph/neo4j_client.py` (phase 0 스텁)
- `/phases/3-graph/index.json`

## 작업

### 1. `src/graph/schema.py` 완성

```python
class NodeLabel:
    POI = "POI"
    AREA = "Area"
    TIME_SLOT = "TimeSlot"

class RelType:
    IN_AREA = "IN_AREA"
    SCHEDULED_AT = "SCHEDULED_AT"
    FOLLOWED_BY = "FOLLOWED_BY"
    TRAVELS_TO = "TRAVELS_TO"

# 초기화 시 실행할 Neo4j 제약조건·인덱스 (멱등성 보장)
CONSTRAINTS = [
    "CREATE CONSTRAINT poi_id IF NOT EXISTS FOR (p:POI) REQUIRE p.poi_id IS UNIQUE",
    "CREATE CONSTRAINT slot_id IF NOT EXISTS FOR (t:TimeSlot) REQUIRE t.slot_id IS UNIQUE",
    "CREATE INDEX area_name IF NOT EXISTS FOR (a:Area) ON (a.name)",
]
```

### 2. `src/graph/neo4j_client.py` 완성

```python
from neo4j import GraphDatabase
from src.graph.schema import CONSTRAINTS

class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._driver.close()

    def run(self, query: str, **params) -> list[dict]:
        # Session을 열고 query 실행, 결과를 list[dict]로 반환
        ...

    def initialize_schema(self) -> None:
        # CONSTRAINTS 쿼리 모두 실행
        ...

    def health_check(self) -> bool:
        # "RETURN 1" 쿼리로 연결 확인, 성공 시 True, 실패 시 False
        ...
```

### 3. `tests/test_neo4j_schema.py` 작성

`neo4j.GraphDatabase.driver`를 mock으로 대체하여 **실제 Neo4j 없이** 테스트:

```python
from unittest.mock import MagicMock, patch
import pytest

@pytest.fixture
def mock_driver():
    with patch("src.graph.neo4j_client.GraphDatabase") as mock_gdb:
        mock_session = MagicMock()
        mock_driver_inst = MagicMock()
        mock_driver_inst.session.return_value.__enter__.return_value = mock_session
        mock_gdb.driver.return_value = mock_driver_inst
        yield mock_gdb, mock_session, mock_driver_inst
```

테스트 케이스:
- `Neo4jClient("bolt://localhost:7687", "neo4j", "pass")` 생성 → `GraphDatabase.driver` 호출 확인
- `initialize_schema()` → CONSTRAINTS 수 만큼 run 호출
- `health_check()` → True 반환 (mock 기준)
- `Neo4jClient.__enter__` / `__exit__` 동작 확인
- `schema.NodeLabel`, `schema.RelType` 상수값이 ARCHITECTURE.md와 일치하는지 확인 (POI, Area, TimeSlot)

## Acceptance Criteria

```bash
python -m pytest tests/test_neo4j_schema.py -v
```

## 검증 절차

1. 위 AC 커맨드를 실행한다. (mock 기반, 실제 Neo4j 불필요)
2. `phases/3-graph/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- `Neo4jClient`에서 neo4j Session을 외부에 노출하지 마라. 항상 `run()`을 통해서만 쿼리를 실행한다.
- 테스트에서 실제 Neo4j 연결을 시도하지 마라.
- `CONSTRAINTS`에서 `IF NOT EXISTS` 없이 제약조건을 생성하지 마라.
