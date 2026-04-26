<!-- updated: 2026-04-21 | hash: 67cb233e | summary: FastAPI lifespan + /validate, /repair/{plan_id}, /health 라우터 구현 -->
# Step 1: api-routes

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/UI_GUIDE.md` (엔드포인트 스펙)
- `/src/api/schemas.py`
- `/src/data/models.py`
- `/src/explain/orchestrator.py`
- `/src/api/routes.py` (phase 0 스텁)
- `/src/api/main.py` (phase 0 스텁)
- `/phases/6-api/index.json`

## 작업

### 1. `src/api/main.py` 구현

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.data.models import Settings
from src.explain.orchestrator import ValidationOrchestrator

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    orchestrator = ValidationOrchestrator(settings)
    app.state.orchestrator = orchestrator
    app.state.settings = settings
    yield
    # teardown: Neo4j 클라이언트 닫기 (orchestrator._neo4j가 있을 때만)
    if orchestrator._neo4j:
        orchestrator._neo4j.close()

app = FastAPI(
    title="Explainable Travel Plan Validator",
    description="여행 일정의 실행 가능성·동선 효율·위험 요소를 AI로 검증합니다.",
    version="0.1.0",
    lifespan=lifespan,
)
# routes.router include
```

### 2. `src/api/routes.py` 구현

```python
from fastapi import APIRouter, HTTPException, Request
from src.api.schemas import ValidateRequest, ValidateResponse, RepairResponse, HealthResponse
from src.data.models import ItineraryPlan, PlaceInput

router = APIRouter()

@router.post("/validate", response_model=ValidateResponse, status_code=200)
async def validate_plan(request: Request, body: ValidateRequest) -> ValidateResponse:
    """
    여행 일정 검증 전체 파이프라인 실행.
    - TourAPI 404 (ValueError) → HTTPException 404
    - 기타 예외 → HTTPException 503 (서비스 일시 불가)
    """
    orchestrator = request.app.state.orchestrator
    plan = ItineraryPlan(
        places=[PlaceInput(**p.model_dump()) for p in body.places],
        transport=body.transport,
        travel_type=body.travel_type,
        date=body.date,
        start_time=body.start_time,
    )
    try:
        result = await orchestrator.run(plan)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail="서비스를 일시적으로 사용할 수 없습니다.")
    return ValidateResponse.from_result(result)

@router.get("/repair/{plan_id}", response_model=RepairResponse)
async def get_repair(request: Request, plan_id: str) -> RepairResponse:
    """
    저장된 ValidationResult에서 repair_suggestions 반환.
    plan_id 미존재 → HTTPException 404
    """
    # Neo4j에서 plan_id로 저장된 결과 조회
    # MVP: in-memory store 또는 Neo4j 쿼리
    orchestrator = request.app.state.orchestrator
    if not orchestrator._neo4j:
        raise HTTPException(status_code=503, detail="Neo4j 연결 없음")
    # 결과 조회 (Neo4j 또는 캐시)
    # plan_id 없으면 404
    raise HTTPException(status_code=404, detail=f"plan_id={plan_id} 결과 없음")

@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """
    Neo4j, TourAPI, Kakao API 상태 확인.
    모두 정상 → status="ok", 하나 이상 실패 → status="degraded"
    """
    orchestrator = request.app.state.orchestrator
    neo4j_ok = orchestrator._neo4j is not None
    # TourAPI, Kakao: ping 없이 초기화 성공 여부로 판단 (MVP)
    tour_ok = orchestrator._tour is not None
    kakao_ok = orchestrator._kakao is not None
    status = "ok" if all([neo4j_ok, tour_ok, kakao_ok]) else "degraded"
    return HealthResponse(status=status, neo4j=neo4j_ok, tour_api=tour_ok, kakao=kakao_ok)
```

### 3. `tests/test_api_routes.py` 작성

`fastapi.testclient.TestClient` + mock 사용:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from src.api.main import app

VALID_BODY = {
    "places": [
        {"name": "경복궁", "stay_minutes": 120, "visit_order": 1},
        {"name": "인사동", "stay_minutes": 60, "visit_order": 2},
        {"name": "남산서울타워", "stay_minutes": 90, "visit_order": 3},
        {"name": "명동", "stay_minutes": 60, "visit_order": 4},
    ],
    "transport": "transit",
    "travel_type": "cultural",
    "date": "2024-07-20",
}
```

테스트 케이스 (ValidationOrchestrator를 mock):
- `POST /validate` 정상 body → 200 + ValidateResponse 형식
- `POST /validate` places 3개 → 422 ValidationError
- `POST /validate` (TourAPI ValueError) → 404
- `POST /validate` (기타 예외) → 503
- `GET /health` → 200 + `{"status": ...}` 포함
- `GET /repair/{plan_id}` Neo4j 없음 → 503

## Acceptance Criteria

```bash
python -m pytest tests/test_api_routes.py -v
ruff check src/api/
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 전체 테스트 스위트 실행:
   ```bash
   python -m pytest tests/ -v --tb=short
   ```
   모든 테스트 통과 확인.
3. `phases/6-api/index.json`의 step 1 status를 업데이트한다.

## 금지사항

- `routes.py`에서 `ValidationOrchestrator`를 직접 인스턴스화하지 마라. 반드시 `request.app.state.orchestrator`를 사용한다.
- `ValueError`를 503으로 처리하지 마라. TourAPI 관광지 미검색은 404다.
- 전역 변수에 orchestrator 인스턴스를 저장하지 마라. FastAPI lifespan + app.state 사용.
- `GET /repair/{plan_id}` MVP에서 Neo4j가 없으면 503을 반환한다. 결과 캐싱 로직은 선택 구현.
