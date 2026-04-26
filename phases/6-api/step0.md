<!-- updated: 2026-04-21 | hash: 9bd893c4 | summary: FastAPI Request/Response Pydantic 스키마 구현 (ValidateRequest/ValidateResponse) -->
# Step 0: api-schemas

## 읽어야 할 파일

- `/CLAUDE.md`
- `/docs/UI_GUIDE.md` (엔드포인트 Request/Response 스펙)
- `/src/data/models.py`
- `/src/api/schemas.py` (phase 0 스텁)
- `/phases/6-api/index.json`

## 작업

`src/api/schemas.py`에 FastAPI Request/Response Pydantic 스키마를 구현하라.

### 구현할 스키마

```python
from pydantic import BaseModel, Field
from src.data.models import HardFail, Warning, Scores, RepairSuggestion

class PlaceInputSchema(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["경복궁"])
    stay_minutes: int = Field(..., ge=10, le=600)
    visit_order: int = Field(..., ge=1)

class ValidateRequest(BaseModel):
    places: list[PlaceInputSchema] = Field(..., min_length=4, max_length=8)
    transport: str = Field(..., pattern="^(transit|car|walk)$")
    travel_type: str = Field(..., pattern="^(cultural|nature|shopping|food|adventure)$")
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", examples=["2024-07-20"])
    start_time: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")

class ValidateResponse(BaseModel):
    plan_id: str
    final_score: int = Field(ge=0, le=100)
    hard_fails: list[HardFail]
    warnings: list[Warning]
    scores: Scores
    explanation: str
    repair_suggestions: list[RepairSuggestion]

    @classmethod
    def from_result(cls, result) -> "ValidateResponse":
        """ValidationResult → ValidateResponse 변환."""
        return cls(
            plan_id=result.plan_id,
            final_score=result.final_score,
            hard_fails=result.hard_fails,
            warnings=result.warnings,
            scores=result.scores,
            explanation=result.explanation,
            repair_suggestions=result.repair_suggestions,
        )

class RepairResponse(BaseModel):
    plan_id: str
    repair_suggestions: list[RepairSuggestion]

class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    neo4j: bool
    tour_api: bool
    kakao: bool
```

### `tests/test_api_schemas.py` 작성

```python
import pytest
from pydantic import ValidationError
from src.api.schemas import ValidateRequest, ValidateResponse, HealthResponse

def make_places(n=4):
    return [
        {"name": f"장소{i}", "stay_minutes": 60, "visit_order": i}
        for i in range(1, n + 1)
    ]

def test_validate_request_valid():
    req = ValidateRequest(
        places=make_places(4),
        transport="transit",
        travel_type="cultural",
        date="2024-07-20",
    )
    assert req.start_time == "09:00"

def test_validate_request_too_few_places():
    with pytest.raises(ValidationError):
        ValidateRequest(
            places=make_places(3),  # 4 미만
            transport="transit",
            travel_type="cultural",
            date="2024-07-20",
        )

def test_validate_request_too_many_places():
    with pytest.raises(ValidationError):
        ValidateRequest(
            places=make_places(9),  # 8 초과
            transport="transit",
            travel_type="cultural",
            date="2024-07-20",
        )

def test_validate_request_invalid_transport():
    with pytest.raises(ValidationError):
        ValidateRequest(
            places=make_places(4),
            transport="bike",  # 허용 안 됨
            travel_type="cultural",
            date="2024-07-20",
        )

def test_validate_request_invalid_date_format():
    with pytest.raises(ValidationError):
        ValidateRequest(
            places=make_places(4),
            transport="transit",
            travel_type="cultural",
            date="20240720",  # 잘못된 형식
        )

def test_health_response():
    h = HealthResponse(status="ok", neo4j=True, tour_api=True, kakao=True)
    assert h.status == "ok"
```

테스트 케이스:
- `ValidateRequest` 정상 생성 (4개 장소)
- `places` 3개 미만 → ValidationError
- `places` 9개 초과 → ValidationError
- `transport="bike"` → ValidationError
- `date="20240720"` (잘못된 형식) → ValidationError
- `ValidateResponse.from_result(mock_result)` → ValidateResponse 생성
- JSON 직렬화 → final_score, hard_fails 포함 확인

## Acceptance Criteria

```bash
python -m pytest tests/test_api_schemas.py -v
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. `phases/6-api/index.json`의 step 0 status를 업데이트한다.

## 금지사항

- `src/data/models.py`의 `ValidationResult`를 API 응답으로 직접 반환하지 마라. `ValidateResponse.from_result()`로 변환 후 반환한다.
- `ValidateRequest`에서 places가 3개 이하일 때 ValidationError가 아닌 다른 에러를 발생시키지 마라.
- `transport` 필드를 문자열로만 허용하고 Enum으로 강제하지 마라 (openapi 스펙 단순화).
