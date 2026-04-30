<!-- updated: 2026-04-30 | hash: bf153a9c | summary: cluster_dispersion M1-M4 완성, M4 DBSCAN per-request 구현 + M3 중복 방지 명시 -->

1. 프로젝트 비전
  "우리는 여행을 추천하지 않는다. 그 일정이 실패할지, 성공할지를 증명한다."
  사용자가 수립한 여행 일정의 실행 가능성(Feasibility), 효율성(Efficiency), 목적 적합성(Purpose Fit)을
  데이터와 규칙 기반으로 검증하고, AI(LLM)를 통해 설명 가능한(Explainable) 피드백을 제공하는
  QA 레이어 시스템입니다.

2. 핵심 기능 및 구현 전략

  ① 일정 검증 (Validation)
   - Hard Fail (Critical): 운영시간 충돌, 이동 불가 등 물리적으로 실행 불가능한 요소 탐지.
   - Soft Warning: 동선 비효율(Backtracking), 일정 과밀, 체력 부담 등 품질 저하 요소 탐지.
   - 구현 방식:
       - HardFailDetector: 운영시간 및 이동 시간 윈도우 기반 제약 조건 검사.
         체류시간 비현실성(dwell_db 권장 최소의 50% 미만 입력) 포함.
       - WarningDetector: 동선 흐름(Flow) 및 지역 밀도(Area Intensity) 분석.

  ② 점수 산정 (Scoring)
   - 4개 지표(travel_ratio, cluster_dispersion, theme_alignment, Congestion Coefficient)로 패널티 구조의 Risk Score 산출.
   - 구현 방식:
       - VRPTWEngine: OR-Tools를 사용해 수학적 최적 경로와 사용자 경로의 격차(Efficiency Gap) 계산.
          최적 경로는 강제 대체안이 아닌, 사용자 일정의 기회비용 벤치마크로 활용.
       - 목적: 사용자 경로와 OR-Tools 최적 경로의 Efficiency Gap을 수치로 산출해 이동 낭비의 기회비용을 제시.

       - cluster_dispersion : 4개 메트릭으로 하루 일정의 지리적 밀집도를 평가. 위반 합산 캡 -20.
         - M1. sigungu_switches: 같은 day 안 시군구 전환 횟수 (≥3회 WARNING -5 / ≥4회 CRITICAL -10).
         - M2. max_pairwise_distance_km: Haversine 기반 하루 안 최대 직선거리 (≥30km -5 / ≥50km -10 / ≥100km -20).
         - M3. area_backtrack_count: 시군구 코드 기반 비연속 재진입 (O(n)). "강남→홍대→강남"=1회 -5, 2회+ -10.
               순방향 4구역 순회(강남→이태원→명동→종로)=0회 → False-positive 없음.
         - M4. geo_cluster_backtrack: DBSCAN(eps=2km, haversine) 지리 클러스터 비연속 재진입.
               M3 보완: 경주·제주 등 대형 시군구 내부 지리 분산 탐지. M3가 이미 탐지한 이벤트는 net=max(0, count-m3_count)로 중복 패널티 제외.
               per-request 즉석 계산 (4~8 POI → <1ms). DB 사전 클러스터링 불필요.

       - ThemeAlignmentJudge: Claude API + Naver 블로그 KB(summary_text RAG 임베딩)를 활용해 사용자 테마와 POI 카테고리 간의 의미적 일치도 판정.
         - 예시: "방문자 리뷰에서 체력 소모가 크고 어린이 동반 어렵다는 언급이 다수입니다. 가족 힐링 테마와 불일치 가능성 있음."
         - ※ LLM 판정 유일 예외: 본 시스템은 원칙적으로 LLM을 설명 생성에만 사용하지만(section 5),
           테마-장소 간 의미적 일치도는 규칙으로 정량화할 수 없어 LLM이 직접 0.0~1.0 점수를 판정하는
           유일한 예외로 설계한다. 단, 판정 근거(장소 카테고리·테마 정의)는 명시적으로 프롬프트에 주입하여
           LLM의 임의적 추론이 아닌 제공된 사실에 기반한 판정임을 보장한다.
    
       - Congestion Coefficient : 시계열 데이터의 월별 방문객 추이를 '혼잡 계수(Congestion Coefficient)'라는 정규화된 값(0.0~1.0)으로 테이블화
         - Rule Engine: 사용자 방문 예정월(Month)과 POI를 입력받아 5개년 통계 기반 혼잡도를 판정 (`src/scoring/congestion_engine.py`).
           - 서울 소재 POI는 서울 도시데이터 API(실시간 인구 + 12시간 예측)를 우선 적용, 미커버 POI는 한국문화관광연구원 2020~2024 PDF 통계로 폴백.
         - LLM 연동: "해당 월은 통계적으로 전년 대비 방문객이 30% 증가하는 기간입니다. 이에 따라 보수적인 이동 시간을 제안합니다"라는 근거를 생성합니다.

  ③ 설명 엔진 (Explain Engine)
   - 모든 판정 결과를 [사실(Fact) → 규칙(Rule) → 위험(Risk) → 제안(Suggestion)] 4단계 구조로 출력.
   - 구현 방식: Claude API를 활용하여 정형화된 검증 데이터(JSON)를 자연어 보고서로 변환.
     수정 제안은 최소 간섭 원칙(Re-ordering(순서 변경) → Stay-time Tuning(체류 시간 조정) → Deletion(삭제) 순)으로 제시.
   - 고도화: 
    - 동선 지도(GeoJSON) 생성 : 시스템이 판단한 '비효율 경로(백트래킹)'를 시각적으로 보여주는 GeoJSON 데이터를 생성하여, API 응답으로 같이 내보내십시오. 이는 프론트엔드에서 즉시 지도로 시각화가 가능합니다.

3. 데이터 활용 구조

  ① 외부 API 데이터
   - TourAPI (한국관광공사): POI 기본 메타데이터(운영시간, 카테고리, 좌표) 수집.
   - Kakao Local/Mobility: 좌표 정규화 및 실제 이동 시간/거리 행렬(Distance Matrix) 생성.
   - 데이터 신뢰도 3단계:
       High   — Kakao 실시간 API 성공 + TourAPI 운영시간 정상 제공
       Medium — 캐시 경로 사용 또는 dwell_db 추정값 적용 (결과에 "(추정)" 표시)
       Low    — Haversine 폴백 또는 지오코딩 실패 (경고 메시지 출력)

  ② 로컬 지식 베이스 (Knowledge Base)
   - Dwell DB (Supabase 전환): POI 카테고리별/개별 POI별 권장 체류 시간 데이터베이스.
    - 구조: poi_id, category_id, min_duration, max_duration, priority 컬럼으로 구성.
    - 폴백 로직: SQL ORDER BY priority ASC LIMIT 1 쿼리를 통해 수동 오버라이드 → 상세 카테고리(lclsSystm3) → 대분류(lclsSystm1) → 기본값 순으로 결정.
    - 성능 최적화: Supabase Realtime 또는 주기적 데이터 동기화를 통해 애플리케이션 레벨의 로컬 캐시(In-memory)를 유지하여 조회 성능(Latency)보장.
    - 관리: 50개 이상의 핵심 POI 수동 큐레이션 데이터를 대시보드에서 직접 관리하여 유지보수성 극대화.


   - 한국문화관광연구원 pdf: '목적 적합성(Purpose Fit)' 평가 기준 마련. 
    - 특정 지역(예: 경주)의 연도별/월별 입장객 통계 데이터를 로컬 DB에 넣어두고, 사용자가 방문하려는 시점의 '비수기/성수기 방문객 패턴'을 분석. "성수기인 5월 방문 시 평균 입장 대기 시간이 20% 증가함"이라는 통계적 증거 제시.

   - Naver 블로그 KB: 1,000개 POI 대상 규칙 기반 메타데이터 수집. 샘플 검증 후 최적 검색 로직을 통해 전체 장소 정보 탐색 예정
     필드: waiting(웨이팅이 있는지?) / crowd_level(사람들이 붐비는지?) / reservation_required(예약해야하는지?) / parking(주차할 수 있는지?) / price_level(가격이 어떤지?) / sentiment(부정적인 평가가 있는지?) / summary_text.
     sentiment는 부정 신호(≥2회 키워드 출현)만 수집 — 블로그 긍정 편향으로 긍정 신호 신뢰 불가하므로 부정신호만 탐색 후 팩트판단.
     summary_text는 RAG 임베딩용 자연어 요약 (Supabase DB 등 벡터 DB 저장 대상).
   - Theme Taxonomy: 여행 테마별 권장 POI 타입 및 스타일 매핑 테이블.

  ③ 백트래킹·동선 역행 탐지 — Python 순수 구현 (Neo4j 불필요)
   - 커버리지 검증 결과 (scripts/neo4j_coverage_analysis.py): Python 로직이 Neo4j 설계 역할 100% 커버 확인 후 제거 확정.
   - M3 `area_backtrack_count` (`src/scoring/cluster_dispersion.py`):
       · 비연속 구역 재진입 횟수를 시군구 코드 기반으로 O(n) 탐지.
       · "강남 → 홍대 → 강남" = 1회 → WARNING(-5), 2회 이상 → CRITICAL(-10).
       · 순방향 4구역 순회(강남→이태원→명동→종로) = 0회 → 패널티 없음 (False-positive 없음).
   - M4 `geo_cluster_backtrack` (`src/scoring/cluster_dispersion.py`):
       · DBSCAN(eps=2km, haversine)으로 지리 클러스터 비연속 재진입 탐지.
       · M3 보완: 경주·제주처럼 시군구가 넓어 M3가 탐지 못하는 내부 지리 분산 케이스 커버.
       · M3 중복 방지: net = max(0, M4_count - M3_count)로 순증분만 패널티 부과.
   - 동선 역행(지리 분산): M2 `max_pairwise_distance_km` + M4 `geo_cluster_backtrack` 조합으로 커버.
   - 시간대 과밀: `travel_ratio` 임계값(20%) + VRPTW `fatigue` 탐지로 커버.

4. 설계 철학

  ① 기회비용 중심의 벤치마킹 (Benchmarking Opportunity Cost)
   - AI는 판단하지 않습니다: 사용자의 동선이 비효율적일 때, 시스템은 감점 대신
     "이 순서를 유지하기 위해 최적 경로 대비 40분의 이동 시간이 추가로 소요됩니다, "라는 데이터 증거를 제시합니다.
   - 판단은 사용자의 몫: 추가 소요 시간 정보를 제공함으로써, 사용자가 해당 장소의
     가치와 이동 시간 사이의 트레이드오프를 직접 결정하게 돕습니다.

  ② 최소 간섭 수정 전략 (Minimal Interference Repair)
   - 의도 보존 우선: 수정 제안(Repair) 시 사용자가 선택한 POI 목록을 삭제하는 대신,
     아래의 우선순위에 따라 일정의 실행 가능성을 확보합니다.
       1. 순서 재배치(Re-ordering): 장소는 그대로 유지하고 방문 순서만 최적화.
       2. 체류 시간 조정(Stay-time Tuning): 권장 체류 시간 범위 내에서 시간을 미세 조정.
       3. 장소 삭제(Deletion): 물리적 한계로 불가능할 경우에만 최후의 수단으로 삭제 제안.

5. 핵심 기술 구현 방식

   - VRPTW Benchmark Engine: OR-Tools를 최적 경로 생성기가 아닌, 사용자 일정의 효율성을
     측정하는 비교 척도(Baseline)로 활용. 평균 POI 4.3개 수준에서 밀리초 내 최적해 계산 가능.
   - Evidence-based Explainability: 판정의 근거를 [사실(Fact) → 규칙(Rule) → 위험(Risk) →
     제안(Suggestion)]으로 구조화하여, AI의 제안이 객관적 데이터에 기반함을 증명.
   - LLM 역할 분리: 수치 계산(이동 시간·체류시간·Efficiency Gap)은 결정론적 규칙 엔진이 담당.
     Claude API는 규칙 엔진이 산출한 구조화 JSON을 자연어 설명과 수정 제안으로 변환하는 역할만 수행.
     이 구조는 재현 가능성과 설명 가능성을 동시에 보장한다.
