-- Supabase Migration: POI 혼잡도 기준 데이터
-- 실행 전: scripts/extract_visitor_stats.py 로 congestion_stats.csv 생성 필요
-- 적용: supabase db push 또는 Supabase Dashboard > SQL Editor

-- 1. 테이블 생성
CREATE TABLE IF NOT EXISTS poi_congestion_stats (
    id              BIGSERIAL PRIMARY KEY,
    poi_name        TEXT        NOT NULL,
    month           SMALLINT    NOT NULL CHECK (month BETWEEN 1 AND 12),
    avg_visitors    NUMERIC(12, 1) NOT NULL,
    congestion_score NUMERIC(5, 4)  NOT NULL CHECK (congestion_score BETWEEN 0 AND 1),
    annual_max      NUMERIC(14, 1),
    annual_min      NUMERIC(14, 1),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (poi_name, month)
);

-- 2. 인덱스
CREATE INDEX IF NOT EXISTS idx_poc_poi_name  ON poi_congestion_stats (poi_name);
CREATE INDEX IF NOT EXISTS idx_poc_month     ON poi_congestion_stats (month);
CREATE INDEX IF NOT EXISTS idx_poc_score     ON poi_congestion_stats (congestion_score DESC);

-- 3. RLS (읽기 전용 공개)
ALTER TABLE poi_congestion_stats ENABLE ROW LEVEL SECURITY;

CREATE POLICY "public read-only"
    ON poi_congestion_stats FOR SELECT
    USING (true);

-- 4. CSV 업로드 후 upsert 예시 (Python / psycopg2)
-- COPY poi_congestion_stats (poi_name, month, avg_visitors, congestion_score, annual_max, annual_min)
-- FROM '/path/to/congestion_stats.csv'
-- WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

-- 또는 pandas → supabase-py 방식:
-- supabase.table("poi_congestion_stats").upsert(records, on_conflict="poi_name,month").execute()

-- 5. 조회 예시: 5월 혼잡도 상위 20
-- SELECT poi_name, avg_visitors, congestion_score
-- FROM poi_congestion_stats
-- WHERE month = 5
-- ORDER BY congestion_score DESC
-- LIMIT 20;
