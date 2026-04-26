"""품질 평가 (Scoring) 레이어.

VRPTW 검증을 통과한 일정에 대해 "얼마나 좋은 경로인가" 평가:
  - travel_ratio       : 이동 vs 관광 시간 비율
  - cluster_dispersion : 일별 공간 응집도 (per-day)
  - theme_alignment    : 테마 일치성 (LLM 판정)
"""
