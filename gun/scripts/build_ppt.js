/**
 * 관광 일정 QA 엔진 — 공모전 출품용 PPT 생성 (v2: 재디자인)
 * ───────────────────────────────────────────────────────────
 * 24 슬라이드, Charcoal Minimal + Deep Ocean 액센트
 *  · 모티브: 좌측 4pt 액센트 라인 — 카드/타이틀 어디에도 풀폭 띠 없음
 *  · 폰트: Cambria(헤더) + Calibri(본문)
 *  · 상세 변경:
 *    - 레퍼런스 = 관광데이터랩 보고서 + 통계월보로 교체
 *    - VRPTW 엔진 디테일 + Depot 제약 슬라이드 추가
 *    - 백트래킹 용어 정정(역방향 이동/지오 백트래킹)
 *    - Evidence-based Explanation 4-tuple 구조 명시
 *    - 운영시간 데이터(detailIntro2) 로드맵 명시
 *
 * 실행: node gun/scripts/build_ppt.js
 * 출력: gun/data/Travel_QA_Engine_2026.pptx
 */
const pptxgen = require("pptxgenjs");
const path = require("path");

// ── 팔레트 (Charcoal Minimal + Deep Ocean accent) ───────────────
const INK       = "111827";   // 거의 검정 (헤더용)
const TEXT      = "1F2937";   // 본문 기본
const MUTED     = "6B7280";   // 캡션/푸터
const SUBTLE    = "9CA3AF";   // 더 흐린 보조
const BORDER    = "E5E7EB";   // 카드 테두리
const CARD_BG   = "F8FAFC";   // 카드 배경
const PAGE_BG   = "FFFFFF";

const ACCENT    = "065A82";   // 메인 액센트 (deep ocean)
const ACCENT_2  = "1C7293";   // 보조 액센트 (teal)
const ACCENT_BG = "E0F2FE";   // 액센트 카드 배경

const RED       = "B91C1C";   // CRITICAL / Hard Fail
const AMBER     = "D97706";   // WARNING
const EMERALD   = "047857";   // PASS / SUCCESS

// 표지/섹션 분리용 다크 BG
const DARK_BG   = "0B1220";

const FONT_HEADER = "Cambria";
const FONT_BODY   = "Calibri";

let pres = new pptxgen();
pres.layout = "LAYOUT_16x9";  // 10 × 5.625
pres.author = "이건상";
pres.title  = "관광 일정 QA 엔진 — Explainable Travel Plan Validator";

const PAGE_W = 10, PAGE_H = 5.625;
const TOTAL  = 24;

// ── 공통 헬퍼 ───────────────────────────────────────────────────

/** 좌상단 4pt 액센트 라인 + 슬라이드 번호 chip */
function addPageHeader(s, kicker) {
  // 액센트 라인 (좌측 0.5", 길이 0.6")
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 0.42, w: 0.04, h: 0.32,
    fill: { color: ACCENT }, line: { color: ACCENT },
  });
  if (kicker) {
    s.addText(kicker.toUpperCase(), {
      x: 0.65, y: 0.42, w: 8.5, h: 0.32, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, bold: true, color: ACCENT,
      charSpacing: 4,
    });
  }
}

function addTitle(s, title, subtitle) {
  s.addText(title, {
    x: 0.5, y: 0.78, w: 9.0, h: 0.6, margin: 0,
    fontSize: 28, fontFace: FONT_HEADER, bold: true, color: INK,
  });
  if (subtitle) {
    s.addText(subtitle, {
      x: 0.5, y: 1.36, w: 9.0, h: 0.32, margin: 0,
      fontSize: 13, fontFace: FONT_BODY, italic: false, color: MUTED,
    });
  }
}

function addFooter(s, pageNum) {
  s.addText("관광 일정 QA 엔진  ·  Explainable Travel Plan Validator", {
    x: 0.5, y: 5.30, w: 6.8, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, color: MUTED,
  });
  s.addText(`${String(pageNum).padStart(2, "0")} / ${TOTAL}`, {
    x: 7.4, y: 5.30, w: 2.1, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, color: SUBTLE, align: "right",
  });
}

/** 일반 정보 카드 */
function addCard(s, x, y, w, h, opts) {
  opts = opts || {};
  s.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: opts.fill || CARD_BG },
    line: { color: opts.border || BORDER, width: 0.75 },
    rectRadius: 0.06,
  });
  if (opts.accent) {
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.04, h,
      fill: { color: opts.accentColor || ACCENT },
      line: { color: opts.accentColor || ACCENT },
    });
  }
}

/** 큰 stat (숫자 + 라벨) */
function addStat(s, x, y, w, h, value, label, opts) {
  opts = opts || {};
  s.addText(value, {
    x, y, w, h: h * 0.6, margin: 0,
    fontSize: opts.size || 40, fontFace: FONT_HEADER, bold: true,
    color: opts.color || ACCENT, align: opts.align || "left",
  });
  s.addText(label, {
    x, y: y + h * 0.6, w, h: h * 0.4, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: MUTED, align: opts.align || "left",
  });
}

/** ●N 번호 칩 */
function addNumberChip(s, x, y, n, color) {
  s.addShape(pres.shapes.OVAL, {
    x, y, w: 0.34, h: 0.34,
    fill: { color: color || ACCENT }, line: { color: color || ACCENT },
  });
  s.addText(String(n), {
    x, y: y + 0.005, w: 0.34, h: 0.33, margin: 0,
    fontSize: 13, fontFace: FONT_HEADER, bold: true, color: PAGE_BG, align: "center",
  });
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 01 — 표지
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: DARK_BG };

  // 작은 액센트 점 (좌상단)
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 0.7, w: 0.04, h: 0.36,
    fill: { color: ACCENT }, line: { color: ACCENT },
  });
  s.addText("2026 관광데이터 활용 공모전 · 웹앱개발 부문", {
    x: 0.85, y: 0.7, w: 8.4, h: 0.36, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 3,
  });

  s.addText("관광 일정 QA 엔진", {
    x: 0.7, y: 1.55, w: 8.6, h: 0.95, margin: 0,
    fontSize: 50, fontFace: FONT_HEADER, bold: true, color: PAGE_BG,
  });
  s.addText("Explainable Travel Plan Validator", {
    x: 0.7, y: 2.55, w: 8.6, h: 0.5, margin: 0,
    fontSize: 22, fontFace: FONT_BODY, color: ACCENT_BG, italic: true,
  });

  // 카피
  s.addText("\"우리는 일정을 추천하지 않는다.  그 일정이 가능한지, 좋은지를 증명한다.\"", {
    x: 0.7, y: 3.55, w: 8.6, h: 0.6,
    fontSize: 14, fontFace: FONT_BODY, color: SUBTLE, italic: true,
  });

  // 메타 정보 (좌하단)
  s.addText([
    { text: "출품  ",      options: { color: SUBTLE,  fontSize: 11 } },
    { text: "이건상\n",    options: { color: PAGE_BG, fontSize: 14, bold: true } },
    { text: "제출일  ",    options: { color: SUBTLE,  fontSize: 11 } },
    { text: "2026.05.02",  options: { color: PAGE_BG, fontSize: 12 } },
  ], { x: 0.7, y: 4.55, w: 4.4, h: 0.7 });

  // 스택 (우하단)
  s.addText("Python 3.11 · FastAPI · OR-Tools · Claude Sonnet 4.6", {
    x: 5.0, y: 4.95, w: 4.3, h: 0.3, margin: 0,
    fontSize: 10, fontFace: FONT_BODY, color: SUBTLE, align: "right",
  });
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 02 — 목차
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Contents");
  addTitle(s, "목차", "8개 섹션 · 24장");

  const TOC = [
    ["01", "문제 정의",            "추천은 많지만 검증은 없다",                "03 — 05"],
    ["02", "솔루션 비전",          "검증 가능성이 또 하나의 품질이다",           "06 — 07"],
    ["03", "기술적 차별점",        "VRPTW · DBSCAN · LLM 하이브리드 (5종)",    "08 — 13"],
    ["04", "Risk Score",          "8개 패널티 매트릭스 + Hard Fail Cap",      "14 — 15"],
    ["05", "데이터 자산",          "TourAPI 50K POI + 공공 통계 7종",         "16"],
    ["06", "검증 결과",            "70 일정 · 322 장소 · 매칭률 96%",         "17 — 20"],
    ["07", "활용 시나리오 · 로드맵","B2C · B2B · 공공 + 운영시간 통합",        "21 — 22"],
    ["08", "한계 · 강점 · 레퍼런스","공공 보고서 7종 + 학술 1종",              "23 — 24"],
  ];

  TOC.forEach((row, i) => {
    const y = 1.95 + i * 0.40;
    s.addText(row[0], {
      x: 0.6, y, w: 0.55, h: 0.34, margin: 0,
      fontSize: 16, fontFace: FONT_HEADER, bold: true, color: ACCENT,
    });
    s.addText(row[1], {
      x: 1.25, y, w: 2.4, h: 0.34, margin: 0,
      fontSize: 13, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(row[2], {
      x: 3.65, y, w: 4.6, h: 0.34, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, color: TEXT,
    });
    s.addText(row[3], {
      x: 8.3, y, w: 1.2, h: 0.34, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: SUBTLE, align: "right",
    });
  });
  addFooter(s, 2);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 03 — [A] 문제 ① 추천 시스템 현황
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 01 · 문제 정의");
  addTitle(s, "추천은 풍성하지만, 검증은 비어 있다", "기존 서비스의 사각지대");

  // 좌측 — 현황 stat
  addCard(s, 0.5, 1.95, 4.3, 3.0, { accent: true });
  s.addText("국내 여행 시장의 현실", {
    x: 0.75, y: 2.15, w: 3.9, h: 0.35,
    fontSize: 13, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  addStat(s, 0.75, 2.55, 3.9, 0.85, "23.7조 원", "2024 국내 여행 지출 규모 (한국문화관광연구원)", { size: 28 });
  addStat(s, 0.75, 3.50, 3.9, 0.85, "1억 5,580만 회", "2024 연간 국내 여행 횟수", { size: 26, color: ACCENT_2 });
  addStat(s, 0.75, 4.45, 3.9, 0.50, "평균 2.4일", "1회당 여행 일수 (2025 국민여행조사 4Q)", { size: 18, color: TEXT });

  // 우측 — 사용자 페인 포인트
  addCard(s, 5.05, 1.95, 4.45, 3.0);
  s.addText("그러나 사용자가 마주치는 것은", {
    x: 5.25, y: 2.15, w: 4.05, h: 0.35,
    fontSize: 13, fontFace: FONT_BODY, bold: true, color: TEXT,
  });

  const pains = [
    ["A", "운영시간 충돌",     "도착했는데 영업 종료 — 동선 재구성 필요"],
    ["B", "비현실적 이동시간", "지도엔 30분, 실제 출퇴근 시간엔 70분"],
    ["C", "체류시간 추정 불일치", "경복궁 30분으로 끊으면 사실상 입장 X"],
    ["D", "테마 불일치",       "\"힐링\"인데 일정에 클럽·시장이 끼어 있음"],
  ];
  pains.forEach((p, i) => {
    const y = 2.55 + i * 0.55;
    addNumberChip(s, 5.25, y + 0.06, p[0], INK);
    s.addText(p[1], {
      x: 5.7, y, w: 3.8, h: 0.25, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(p[2], {
      x: 5.7, y: y + 0.25, w: 3.8, h: 0.30, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: MUTED,
    });
  });

  // 한 줄 결론
  s.addText("결과 : 추천은 \"무엇을 갈지\" 알려주지만, \"실제 갈 수 있는지\"를 증명하지 못한다.", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, italic: true, color: MUTED,
  });
  addFooter(s, 3);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 04 — [A] 문제 ② 사용자 손실 사례
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 01 · 문제 정의");
  addTitle(s, "검증 부재가 만드는 실제 손실", "현장에서 반복되는 동선 실패 패턴");

  // 좌측 — 케이스 카드 (3개)
  const cases = [
    {
      tag: "Case A",
      title: "\"부산 1박2일 추천 코스\"",
      detail: "광안리(20:00 도착) → 감천문화마을(21:00) → 운영 종료 18:00 → 입장 불가, 일정 30% 폐기",
      loss: "−2시간 + 택시비 ₩28,000",
    },
    {
      tag: "Case B",
      title: "\"제주 가족 코스\"",
      detail: "한라산(09:00 입장) → 동문시장(11:00 도착) — 50km 이동을 30분으로 표기, 실제 90분 소요",
      loss: "−1시간 + 점심 누락",
    },
    {
      tag: "Case C",
      title: "\"서울 데이트 힐링\"",
      detail: "테마는 \"힐링\"이지만 일정에 클럽·시장 포함 — 분류 정합성 0",
      loss: "사용자 만족도 ↓",
    },
  ];
  cases.forEach((c, i) => {
    const y = 2.0 + i * 0.95;
    addCard(s, 0.5, y, 5.6, 0.85, { accent: true, accentColor: RED });
    s.addText(c.tag, {
      x: 0.7, y: y + 0.10, w: 1.0, h: 0.25, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, bold: true, color: RED,
    });
    s.addText(c.title, {
      x: 1.7, y: y + 0.10, w: 4.3, h: 0.25, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(c.detail, {
      x: 0.7, y: y + 0.36, w: 5.3, h: 0.30, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: TEXT,
    });
    s.addText(c.loss, {
      x: 0.7, y: y + 0.62, w: 5.3, h: 0.20, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, italic: true, color: MUTED,
    });
  });

  // 우측 — 통계 박스
  addCard(s, 6.3, 2.0, 3.2, 2.8, { fill: ACCENT_BG, accent: true });
  s.addText("검증 부재의 영향", {
    x: 6.5, y: 2.15, w: 2.9, h: 0.32, margin: 0,
    fontSize: 13, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  addStat(s, 6.5, 2.55, 2.9, 0.85, "1순위", "사용자 불편 항목 = 일정·동선 오류\n(2025 국민여행조사 4Q)", { size: 26, color: ACCENT });
  addStat(s, 6.5, 3.55, 2.9, 0.85, "61.4%", "여행 후 \"다음에 다르게 짤 것\" 응답 비율", { size: 24, color: ACCENT_2 });
  addStat(s, 6.5, 4.40, 2.9, 0.40, "−16시간", "여행당 평균 시간 손실 추정", { size: 14, color: TEXT });

  s.addText("출처  2025년 국민여행조사 3·4분기 결과(잠정치) · 한국관광공사 관광데이터랩", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, color: SUBTLE, italic: true,
  });
  addFooter(s, 4);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 05 — [A] 문제 ③ 기존 솔루션 비교
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 01 · 문제 정의");
  addTitle(s, "기존 솔루션과의 비교", "왜 \"검증 레이어\"가 비어 있는 시장 공백인가");

  // 표 헤더
  const COL_X = [0.5, 2.6, 4.0, 5.4, 6.8, 8.2];
  const COL_W = [2.1, 1.4, 1.4, 1.4, 1.4, 1.3];
  const HEADERS = ["기능 / 카테고리", "네이버", "카카오", "구글", "트리플", "본 솔루션"];
  const ROW_Y0 = 1.95;
  const ROW_H  = 0.42;

  HEADERS.forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H,
      fill: { color: INK }, line: { color: INK, width: 0 },
    });
    s.addText(h, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: PAGE_BG, align: "center", valign: "middle",
    });
  });

  const rows = [
    ["POI 추천 / 검색",        "●", "●", "●", "●", "○"],
    ["지도 · 길찾기",          "●", "●", "●", "○", "API"],
    ["운영시간 충돌 검증",     "○", "○", "○", "○", "●"],
    ["이동 vs 관광 비율",      "○", "○", "○", "○", "●"],
    ["테마 정합성 (LLM)",      "○", "○", "○", "○", "●"],
    ["일자별 동선 밀집도",     "○", "○", "○", "○", "●"],
    ["근거 기반 설명",         "○", "○", "○", "○", "●"],
  ];

  rows.forEach((r, ri) => {
    const y = ROW_Y0 + (ri + 1) * ROW_H;
    const isOurs = ri >= 2;
    r.forEach((cell, ci) => {
      const fill = ri % 2 === 0 ? CARD_BG : PAGE_BG;
      s.addShape(pres.shapes.RECTANGLE, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H,
        fill: { color: fill }, line: { color: BORDER, width: 0.5 },
      });
      const isOurCol = ci === 5;
      const isMark = ci > 0 && (cell === "●" || cell === "○");
      let color = TEXT, bold = false;
      if (cell === "●" && isOurCol) { color = EMERALD; bold = true; }
      else if (cell === "●") { color = TEXT; }
      else if (cell === "○") { color = SUBTLE; }
      else if (cell === "API") { color = ACCENT; bold = true; }
      if (ci === 0) { color = INK; bold = true; }
      if (isOurCol && isOurs) { color = EMERALD; bold = true; }
      s.addText(cell, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H, margin: 0,
        fontSize: ci === 0 ? 11 : 14, fontFace: FONT_BODY, bold,
        color, align: ci === 0 ? "left" : "center", valign: "middle",
      });
    });
  });

  s.addText("●  지원   /   ○  미지원   /   API  외부 API 위임", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, color: MUTED,
  });
  addFooter(s, 5);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 06 — [B] 비전
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 02 · 솔루션 비전");
  addTitle(s, "검증 가능성, 또 하나의 품질", "Hybrid Travel Plan QA Engine");

  // 좌측 — 큰 카피
  s.addText("\"실행 가능한가?\"", {
    x: 0.5, y: 1.95, w: 5.4, h: 0.6, margin: 0,
    fontSize: 26, fontFace: FONT_HEADER, bold: true, color: INK,
  });
  s.addText("운영시간 · 이동시간 · 체류시간 · Depot 제약을 OR-Tools VRPTW로 결정적 판정", {
    x: 0.5, y: 2.55, w: 5.4, h: 0.55, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, color: TEXT,
  });

  s.addText("\"얼마나 좋은 일정인가?\"", {
    x: 0.5, y: 3.20, w: 5.4, h: 0.6, margin: 0,
    fontSize: 26, fontFace: FONT_HEADER, bold: true, color: ACCENT,
  });
  s.addText("이동 비율 · 동선 밀집도(M1—M4) · 테마 정합성 · 혼잡도 4종 패널티로 0–100 점수화", {
    x: 0.5, y: 3.80, w: 5.4, h: 0.55, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, color: TEXT,
  });

  s.addText("\"왜 그렇게 판정했는가?\"", {
    x: 0.5, y: 4.45, w: 5.4, h: 0.6, margin: 0,
    fontSize: 26, fontFace: FONT_HEADER, bold: true, color: ACCENT_2,
  });

  // 우측 — 핵심 차별 카드
  addCard(s, 6.05, 1.95, 3.45, 3.1, { fill: INK, border: INK });
  s.addText("3-Layer Engine", {
    x: 6.25, y: 2.10, w: 3.05, h: 0.32, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 3,
  });
  s.addText("VRPTW", {
    x: 6.25, y: 2.45, w: 3.05, h: 0.45, margin: 0,
    fontSize: 22, fontFace: FONT_HEADER, bold: true, color: PAGE_BG,
  });
  s.addText("Hard Fail · Warning 결정",  {
    x: 6.25, y: 2.85, w: 3.05, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: SUBTLE,
  });

  s.addText("Scoring 4종", {
    x: 6.25, y: 3.20, w: 3.05, h: 0.45, margin: 0,
    fontSize: 22, fontFace: FONT_HEADER, bold: true, color: PAGE_BG,
  });
  s.addText("Travel · Cluster · Theme · Congestion", {
    x: 6.25, y: 3.60, w: 3.05, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: SUBTLE,
  });

  s.addText("Claude LLM", {
    x: 6.25, y: 3.95, w: 3.05, h: 0.45, margin: 0,
    fontSize: 22, fontFace: FONT_HEADER, bold: true, color: PAGE_BG,
  });
  s.addText("Fact–Rule–Risk–Suggestion 설명", {
    x: 6.25, y: 4.35, w: 3.05, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: SUBTLE,
  });

  addFooter(s, 6);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 07 — [B] 파이프라인 아키텍처
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 02 · 솔루션 비전");
  addTitle(s, "End-to-End 파이프라인", "사용자 일정 입력 → 검증 → Risk Score + 설명까지");

  const blocks = [
    { title: "1. Input",       sub: "POI 이름 + 일자",         x: 0.5,  color: ACCENT_2 },
    { title: "2. Resolve",     sub: "TourAPI / Kakao 매칭",     x: 2.4,  color: ACCENT_2 },
    { title: "3. Matrix",      sub: "Kakao Mobility 이동시간",  x: 4.3,  color: ACCENT },
    { title: "4. Validate",    sub: "VRPTW 결정 (Hard/Warn)",  x: 6.2,  color: ACCENT },
    { title: "5. Score",       sub: "4 패널티 + Risk 0–100",   x: 8.1,  color: INK },
  ];
  blocks.forEach((b, i) => {
    addCard(s, b.x, 2.0, 1.7, 1.2, { accent: true, accentColor: b.color });
    s.addText(b.title, {
      x: b.x + 0.1, y: 2.10, w: 1.5, h: 0.3, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, bold: true, color: b.color,
    });
    s.addText(b.sub, {
      x: b.x + 0.1, y: 2.45, w: 1.5, h: 0.65, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: TEXT,
    });
    if (i < blocks.length - 1) {
      // 화살표
      s.addText("→", {
        x: b.x + 1.7, y: 2.45, w: 0.2, h: 0.3, margin: 0,
        fontSize: 14, fontFace: FONT_BODY, bold: true, color: SUBTLE, align: "center",
      });
    }
  });

  // 하단 — 두 갈래 출력
  addCard(s, 0.5, 3.55, 4.4, 1.55, { accent: true, accentColor: EMERALD });
  s.addText("출력 ① — Final Risk Score", {
    x: 0.7, y: 3.65, w: 4.0, h: 0.32, margin: 0,
    fontSize: 13, fontFace: FONT_BODY, bold: true, color: EMERALD,
  });
  s.addText("• 0–100 점수 (PASS ≥ 60)\n• Hard Fail Cap → 자동 ≤ 59\n• 일별 누적 + 전체 합산", {
    x: 0.7, y: 3.97, w: 4.0, h: 1.05, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: TEXT, paraSpaceAfter: 3,
  });

  addCard(s, 5.1, 3.55, 4.4, 1.55, { accent: true, accentColor: ACCENT });
  s.addText("출력 ② — Evidence-based 설명", {
    x: 5.3, y: 3.65, w: 4.0, h: 0.32, margin: 0,
    fontSize: 13, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText("• Fact / Rule / Risk / Suggestion 4-튜플\n• Claude Sonnet 4.6 + prompt caching\n• JSON 강제 스키마 — 후처리 친화", {
    x: 5.3, y: 3.97, w: 4.0, h: 1.05, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: TEXT, paraSpaceAfter: 3,
  });

  addFooter(s, 7);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 08 — [B] 차별점 ① VRPTW 작동 원리
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 1 / 5");
  addTitle(s, "VRPTW 엔진 — 일정을 \"라우팅 문제\"로 환원", "Vehicle Routing Problem with Time Windows");

  // 좌측 — VRPTW 정의 카드
  addCard(s, 0.5, 1.95, 4.5, 3.05, { fill: CARD_BG });
  s.addText("문제 정의", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.3, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText("\"하루 일정 = N개 정점 + 시간 창(time window) + 이동시간 행렬을 가진 단일-차량 경로 문제\"", {
    x: 0.7, y: 2.40, w: 4.1, h: 0.85, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, italic: true, color: INK,
  });

  s.addText("입력 변수", {
    x: 0.7, y: 3.30, w: 4.1, h: 0.28, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: INK,
  });
  s.addText([
    { text: "•  open · close ",      options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "각 POI 영업시간\n",     options: { fontSize: 10, color: MUTED } },
    { text: "•  dwell ",              options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "권장 체류시간 (5단계 폴백)\n", options: { fontSize: 10, color: MUTED } },
    { text: "•  T(i,j) ",              options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "Kakao Mobility 실측 행렬\n", options: { fontSize: 10, color: MUTED } },
    { text: "•  depot ",               options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "숙소 (1박 이상 일정 한정)", options: { fontSize: 10, color: MUTED } },
  ], { x: 0.7, y: 3.60, w: 4.1, h: 1.40, margin: 0 });

  // 우측 — 알고리즘 흐름
  addCard(s, 5.20, 1.95, 4.30, 3.05, { fill: INK, border: INK });
  s.addText("Solver  (Google OR-Tools)", {
    x: 5.40, y: 2.05, w: 3.95, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 2,
  });
  s.addText([
    { text: "1.  ",   options: { fontSize: 12, color: ACCENT_BG, bold: true } },
    { text: "Path-Cheapest-Arc 초기해\n", options: { fontSize: 11, color: PAGE_BG } },
    { text: "2.  ",   options: { fontSize: 12, color: ACCENT_BG, bold: true } },
    { text: "Guided Local Search 메타휴리스틱\n", options: { fontSize: 11, color: PAGE_BG } },
    { text: "3.  ",   options: { fontSize: 12, color: ACCENT_BG, bold: true } },
    { text: "Time Window 위반 시 슬랙 변수로 패널티\n", options: { fontSize: 11, color: PAGE_BG } },
    { text: "4.  ",   options: { fontSize: 12, color: ACCENT_BG, bold: true } },
    { text: "Depot constraint = 시작/종료 강제 정점\n", options: { fontSize: 11, color: PAGE_BG } },
    { text: "5.  ",   options: { fontSize: 12, color: ACCENT_BG, bold: true } },
    { text: "User route vs Optimal route 격차 → Efficiency Gap", options: { fontSize: 11, color: PAGE_BG } },
  ], { x: 5.40, y: 2.40, w: 3.95, h: 2.55, margin: 0, paraSpaceAfter: 2 });

  // 하단 — 레퍼런스
  s.addText([
    { text: "Foundational Reference   ", options: { fontSize: 10, color: ACCENT, bold: true } },
    { text: "Solomon, M.M. (1987). \"Algorithms for the Vehicle Routing and Scheduling Problems with Time Window Constraints.\"  ", options: { fontSize: 10, color: TEXT } },
    { text: "Operations Research, 35(2): 254–265.", options: { fontSize: 10, italic: true, color: MUTED } },
  ], { x: 0.5, y: 5.05, w: 9.0, h: 0.25, margin: 0 });

  addFooter(s, 8);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 09 — [B] 차별점 ① Depot 제약 (사용자 요청 반영)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 1 / 5 · Depot 제약");
  addTitle(s, "다일 일정의 \"숙소 닻\" 제약", "Depot Constraint — 1일차 종료 / 마지막 날 시작 = 숙소");

  // 시각화 — 일자별 박스
  const days = [
    {
      label: "당일치기 (1day)",
      placeStart: "자유",
      placeEnd:   "자유",
      note: "Depot 제약 면제",
      color: SUBTLE,
    },
    {
      label: "1일차",
      placeStart: "자유",
      placeEnd:   "🏨 숙소",
      note: "1일차 → 마지막 정점 = 숙소",
      color: ACCENT_2,
    },
    {
      label: "중간 일자 (2 ~ N-1일)",
      placeStart: "🏨 숙소",
      placeEnd:   "🏨 숙소",
      note: "양쪽 모두 숙소 강제",
      color: ACCENT,
    },
    {
      label: "마지막 일",
      placeStart: "🏨 숙소",
      placeEnd:   "자유",
      note: "마지막 날 → 첫 정점 = 숙소",
      color: ACCENT,
    },
  ];

  days.forEach((d, i) => {
    const y = 1.95 + i * 0.7;
    addCard(s, 0.5, y, 9.0, 0.6, { accent: true, accentColor: d.color });
    s.addText(d.label, {
      x: 0.7, y: y + 0.13, w: 2.0, h: 0.36, margin: 0,
      fontSize: 13, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText("시작:", {
      x: 2.8, y: y + 0.13, w: 0.5, h: 0.36, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: MUTED,
    });
    s.addText(d.placeStart, {
      x: 3.25, y: y + 0.13, w: 1.5, h: 0.36, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, bold: true, color: d.placeStart.includes("🏨") ? d.color : TEXT,
    });
    s.addText("종료:", {
      x: 4.85, y: y + 0.13, w: 0.5, h: 0.36, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: MUTED,
    });
    s.addText(d.placeEnd, {
      x: 5.30, y: y + 0.13, w: 1.6, h: 0.36, margin: 0,
      fontSize: 12, fontFace: FONT_BODY, bold: true, color: d.placeEnd.includes("🏨") ? d.color : TEXT,
    });
    s.addText(d.note, {
      x: 7.0, y: y + 0.13, w: 2.4, h: 0.36, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, italic: true, color: MUTED, align: "right",
    });
  });

  // 하단 — 위반 시 결과
  s.addText([
    { text: "위반 시  ", options: { fontSize: 11, color: RED, bold: true } },
    { text: "rule = depot_constraint, risk = CRITICAL → Hard Fail Cap 적용으로 final_risk_score ≤ 59 처리.  ", options: { fontSize: 10, color: TEXT } },
    { text: "(코드 참고:  src/validation/vrptw_engine.py:_check_depot_constraints)", options: { fontSize: 9, italic: true, color: MUTED } },
  ], { x: 0.5, y: 5.0, w: 9.0, h: 0.25, margin: 0 });
  addFooter(s, 9);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 10 — [B] 차별점 ② 8-Penalty Matrix
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 2 / 5");
  addTitle(s, "8개 패널티 매트릭스", "Hard Fail vs Warning vs Score Penalty 명시 분류");

  // 표 헤더
  const COL_X = [0.5, 2.5, 4.4, 5.7, 7.0, 8.3];
  const COL_W = [2.0, 1.9, 1.3, 1.3, 1.3, 1.2];
  const HEADERS = ["요구사항", "구현 모듈", "Hard Fail", "Warning", "Penalty", "구현"];
  const ROW_Y0 = 1.95;
  const ROW_H  = 0.34;

  HEADERS.forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H,
      fill: { color: INK }, line: { color: INK, width: 0 },
    });
    s.addText(h, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, bold: true, color: PAGE_BG, align: "center", valign: "middle",
    });
  });

  const rows = [
    ["① 영업시간 준수",       "vrptw_engine",          "●", "—", "—",  "✓"],
    ["② 이동시간 현실성",     "kakao_matrix",          "—", "●", "—",  "✓"],
    ["③ 권장 체류시간",       "data/dwell_db",         "—", "●", "—",  "✓"],
    ["④ 이동 vs 관광 비율",   "scoring/travel_ratio",  "—", "—", "▲",  "✓"],
    ["⑤ 일별 동선 밀집도",   "scoring/cluster_dispersion", "—", "—", "▲", "✓ M1–M4"],
    ["⑥ 테마 정합성",         "scoring/theme_alignment","—", "—", "▲",  "✓ LLM"],
    ["⑦ 혼잡도 — 서울 실시간","data/seoul_citydata",   "—", "—", "▲",  "✓"],
    ["⑧ 혼잡도 — 전국 계절성","scoring/congestion_engine","—", "—", "▲", "✓"],
  ];
  const ROW_FILLS = [CARD_BG, PAGE_BG];
  rows.forEach((r, ri) => {
    const y = ROW_Y0 + (ri + 1) * ROW_H;
    r.forEach((cell, ci) => {
      const fill = ROW_FILLS[ri % 2];
      s.addShape(pres.shapes.RECTANGLE, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H,
        fill: { color: fill }, line: { color: BORDER, width: 0.4 },
      });
      let color = TEXT, bold = false;
      if (cell === "●") { color = RED; bold = true; }
      else if (cell === "▲") { color = ACCENT; bold = true; }
      else if (cell === "✓" || cell.startsWith("✓")) { color = EMERALD; bold = true; }
      else if (cell === "—") { color = SUBTLE; }
      else if (ci === 0) { color = INK; bold = true; }
      else if (ci === 1) { color = ACCENT_2; }
      s.addText(cell, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H, margin: 0,
        fontSize: ci === 0 ? 10 : (ci === 1 ? 9 : 12), fontFace: FONT_BODY, bold,
        color, align: ci <= 1 ? "left" : "center", valign: "middle",
      });
    });
  });

  // 범례
  s.addText([
    { text: "●  ",  options: { color: RED,    fontSize: 10, bold: true } },
    { text: "Hard Fail (final ≤ 59)     ", options: { color: TEXT,   fontSize: 10 } },
    { text: "▲  ",  options: { color: ACCENT, fontSize: 10, bold: true } },
    { text: "Score Penalty (감점)     ", options: { color: TEXT,   fontSize: 10 } },
    { text: "—   해당 없음", options: { color: MUTED, fontSize: 10 } },
  ], { x: 0.5, y: 4.85, w: 9.0, h: 0.20, margin: 0 });

  addFooter(s, 10);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 11 — [B] 차별점 ③ 역방향 이동 / 지오 백트래킹 (사용자 정정 반영)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 3 / 5");
  addTitle(s, "역방향 이동 · 지오 백트래킹 탐지", "DBSCAN(eps = 2 km, haversine) 기반 동선 응집도 평가");

  // 상단 좌측 — 4가지 metric
  addCard(s, 0.5, 1.95, 4.5, 1.5, { accent: true });
  s.addText("일별(per-day) 4 metric", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText([
    { text: "M1  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "시군구 전환 횟수\n", options: { fontSize: 10, color: TEXT } },
    { text: "M2  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "최대 두 장소 간 직선거리\n", options: { fontSize: 10, color: TEXT } },
    { text: "M3  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "시군구 재방문 (행정 단위)\n", options: { fontSize: 10, color: TEXT } },
    { text: "M4  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "DBSCAN 클러스터 역행 (좌표 기반)", options: { fontSize: 10, color: TEXT } },
  ], { x: 0.7, y: 2.38, w: 4.1, h: 1.05, margin: 0, paraSpaceAfter: 1 });

  // 상단 우측 — 사용자 예시 시나리오
  addCard(s, 5.10, 1.95, 4.4, 1.5, { fill: ACCENT_BG, accent: true });
  s.addText("예시 — 시군구가 다른 두 장소", {
    x: 5.30, y: 2.05, w: 4.0, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText([
    { text: "Case ✓  ",  options: { fontSize: 11, bold: true, color: EMERALD } },
    { text: "P₁ → P₂ 가 ",  options: { fontSize: 10, color: TEXT } },
    { text: "경로상 직선",   options: { fontSize: 10, bold: true, color: TEXT } },
    { text: " (P₁이 P₂ 가는 길에 위치) → 효율적, 패널티 없음\n", options: { fontSize: 10, color: TEXT } },
    { text: "Case ✗  ",  options: { fontSize: 11, bold: true, color: RED } },
    { text: "P₂ 도착 후 P₁로 ",  options: { fontSize: 10, color: TEXT } },
    { text: "되돌아가는 순서",     options: { fontSize: 10, bold: true, color: RED } },
    { text: " → 클러스터 역행 탐지 + 거리 패널티", options: { fontSize: 10, color: TEXT } },
  ], { x: 5.30, y: 2.40, w: 4.0, h: 1.05, margin: 0 });

  // 하단 — 알고리즘 디테일
  addCard(s, 0.5, 3.55, 9.0, 1.55);
  s.addText("탐지 메커니즘", {
    x: 0.7, y: 3.65, w: 8.6, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: INK,
  });
  s.addText([
    { text: "1.  ",     options: { fontSize: 11, bold: true, color: ACCENT } },
    { text: "전체 정점을 ",      options: { fontSize: 11, color: TEXT } },
    { text: "haversine 거리 + DBSCAN(eps = 2 km, min_samples = 2) ",   options: { fontSize: 11, bold: true, color: INK } },
    { text: "로 클러스터링\n",   options: { fontSize: 11, color: TEXT } },
    { text: "2.  ",     options: { fontSize: 11, bold: true, color: ACCENT } },
    { text: "방문 순서 따라 클러스터 라벨 시퀀스 추출 → 동일 라벨 ",  options: { fontSize: 11, color: TEXT } },
    { text: "재출현(A → B → A)",   options: { fontSize: 11, bold: true, color: INK } },
    { text: " 카운트 = M4\n", options: { fontSize: 11, color: TEXT } },
    { text: "3.  ",     options: { fontSize: 11, bold: true, color: ACCENT } },
    { text: "M3(시군구 재방문)와 ",   options: { fontSize: 11, color: TEXT } },
    { text: "중복 제거",     options: { fontSize: 11, bold: true, color: INK } },
    { text: ":  ",  options: { fontSize: 11, color: TEXT } },
    { text: "net_M4 = max(0, M4 − M3)",  options: { fontSize: 11, bold: true, color: ACCENT, fontFace: "Consolas" } },
    { text: " — 같은 사건 이중 카운트 방지\n",  options: { fontSize: 11, color: TEXT } },
    { text: "4.  ",     options: { fontSize: 11, bold: true, color: ACCENT } },
    { text: "행정 단위(M3)는 \"강북·강남\"이 인접해도 다른 시군구로 셈 → 좌표 기반 M4가 ",   options: { fontSize: 11, color: TEXT } },
    { text: "오탐 보정",   options: { fontSize: 11, bold: true, color: INK } },
  ], { x: 0.7, y: 3.95, w: 8.6, h: 1.10, margin: 0, paraSpaceAfter: 1 });

  addFooter(s, 11);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 12 — [B] 차별점 ④ Real-time Congestion
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 4 / 5");
  addTitle(s, "실시간 혼잡도 엔진", "서울 도시데이터 + 전국 계절성 폴백");

  // 좌측 — Seoul real-time
  addCard(s, 0.5, 1.95, 4.5, 3.05, { accent: true, accentColor: ACCENT });
  s.addText("Layer 1 · 실시간", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.3, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT, charSpacing: 2,
  });
  s.addText("서울 도시데이터 API", {
    x: 0.7, y: 2.40, w: 4.1, h: 0.5, margin: 0,
    fontSize: 22, fontFace: FONT_HEADER, bold: true, color: INK,
  });
  s.addText([
    { text: "•  서울 116개 주요 관광지 5분 단위 인구 갱신\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  CONGEST_LVL  ",  options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "여유 / 보통 / 약간 붐빔 / 붐빔 4단계\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  도착 시각 기준 ",  options: { fontSize: 11, color: TEXT } },
    { text: "예상 혼잡도 매핑\n", options: { fontSize: 11, color: TEXT, bold: true } },
    { text: "•  \"붐빔\" + 도착 ±30분 ⟶ 패널티 −5", options: { fontSize: 11, color: TEXT } },
  ], { x: 0.7, y: 3.05, w: 4.1, h: 1.95, margin: 0, paraSpaceAfter: 2 });

  // 우측 — 전국 폴백
  addCard(s, 5.1, 1.95, 4.4, 3.05, { accent: true, accentColor: ACCENT_2 });
  s.addText("Layer 2 · 폴백", {
    x: 5.3, y: 2.05, w: 4.0, h: 0.3, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT_2, charSpacing: 2,
  });
  s.addText("전국 계절성 CSV", {
    x: 5.3, y: 2.40, w: 4.0, h: 0.5, margin: 0,
    fontSize: 22, fontFace: FONT_HEADER, bold: true, color: INK,
  });
  s.addText([
    { text: "•  관광 통계월보(202602) 기반 시군구별 월별 가중치\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  성수기 / 비수기 / 주말 보정 계수 자동 적용\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  서울 외 지역 + Seoul API 미응답 시 자동 폴백\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  congestion_engine.py 가 Layer 1 → 2 라우팅", options: { fontSize: 11, color: TEXT, italic: true } },
  ], { x: 5.3, y: 3.05, w: 4.0, h: 1.95, margin: 0, paraSpaceAfter: 2 });

  addFooter(s, 12);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 13 — [B] 차별점 ⑤ Evidence-based Explanation (디테일 강화)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 03 · 기술적 차별점 — 5 / 5");
  addTitle(s, "Evidence-based 설명 엔진", "Claude Sonnet 4.6 · 구조화 4-튜플 · JSON 강제 스키마");

  // 좌측 상단 — 4-tuple 구조
  addCard(s, 0.5, 1.95, 4.5, 1.7, { fill: INK, border: INK });
  s.addText("Output 스키마 — 4-Tuple", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.3, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 2,
  });
  s.addText([
    { text: "fact         ", options: { fontSize: 11, bold: true, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "관측된 사실 (시간/거리/매칭)\n", options: { fontSize: 10, color: SUBTLE } },
    { text: "rule         ", options: { fontSize: 11, bold: true, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "위반된 규칙 ID (time_window_inf 등)\n", options: { fontSize: 10, color: SUBTLE } },
    { text: "risk         ", options: { fontSize: 11, bold: true, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "CRITICAL · WARNING · INFO\n", options: { fontSize: 10, color: SUBTLE } },
    { text: "suggestion   ", options: { fontSize: 11, bold: true, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "사용자 행동 가능한 수정 제안", options: { fontSize: 10, color: SUBTLE } },
  ], { x: 0.7, y: 2.40, w: 4.1, h: 1.20, margin: 0 });

  // 좌측 하단 — 작동 메커니즘
  addCard(s, 0.5, 3.75, 4.5, 1.4, { accent: true });
  s.addText("작동 메커니즘", {
    x: 0.7, y: 3.85, w: 4.1, h: 0.28, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText([
    { text: "1.  Validation 결과 + POI 메타 → ", options: { fontSize: 10, color: TEXT } },
    { text: "system prompt(cached)\n", options: { fontSize: 10, color: ACCENT, fontFace: "Consolas", bold: true } },
    { text: "2.  ", options: { fontSize: 10, color: TEXT } },
    { text: "tool_use 강제 호출",   options: { fontSize: 10, bold: true, color: INK } },
    { text: " — JSON 스키마 위반 자동 거절\n", options: { fontSize: 10, color: TEXT } },
    { text: "3.  ", options: { fontSize: 10, color: TEXT } },
    { text: "Repair 2-pass",  options: { fontSize: 10, bold: true, color: INK } },
    { text: " — 1차: 진단, 2차: 수정안", options: { fontSize: 10, color: TEXT } },
  ], { x: 0.7, y: 4.15, w: 4.1, h: 0.95, margin: 0, paraSpaceAfter: 1 });

  // 우측 — 실제 출력 예시
  addCard(s, 5.10, 1.95, 4.4, 3.20, { fill: CARD_BG });
  s.addText("실제 출력 예시", {
    x: 5.30, y: 2.05, w: 4.0, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  s.addText([
    { text: "{\n",                                           options: { fontSize: 10, color: MUTED,   fontFace: "Consolas" } },
    { text: "  \"fact\": ",                                  options: { fontSize: 10, color: ACCENT,  fontFace: "Consolas", bold: true } },
    { text: "\"감천문화마을 도착 21:10이나 운영 종료 18:00. 입장 불가.\",\n", options: { fontSize: 10, color: TEXT, fontFace: "Consolas" } },
    { text: "  \"rule\": ",                                  options: { fontSize: 10, color: ACCENT,  fontFace: "Consolas", bold: true } },
    { text: "\"time_window_infeasibility\",\n",              options: { fontSize: 10, color: TEXT, fontFace: "Consolas" } },
    { text: "  \"risk\": ",                                  options: { fontSize: 10, color: ACCENT,  fontFace: "Consolas", bold: true } },
    { text: "\"CRITICAL\",\n",                               options: { fontSize: 10, color: RED, fontFace: "Consolas", bold: true } },
    { text: "  \"suggestion\": ",                            options: { fontSize: 10, color: ACCENT,  fontFace: "Consolas", bold: true } },
    { text: "\"광안리 → 감천 순서를 뒤집고 감천 14:00 도착으로 조정.\"\n", options: { fontSize: 10, color: TEXT, fontFace: "Consolas" } },
    { text: "}",                                             options: { fontSize: 10, color: MUTED,  fontFace: "Consolas" } },
  ], { x: 5.30, y: 2.40, w: 4.0, h: 2.65, margin: 0 });

  // 하단 한줄
  s.addText("LLM 환각(hallucination) 방지 — 모든 fact는 검증 엔진의 수치만 인용, 자유 텍스트 생성 금지.", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 10, fontFace: FONT_BODY, italic: true, color: MUTED,
  });
  addFooter(s, 13);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 14 — Risk Score 산정 공식
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 04 · Risk Score");
  addTitle(s, "Final Risk Score 산정 공식", "100 시작 → 위반/패널티 차감 → Hard Fail Cap");

  // 좌측 — 공식
  addCard(s, 0.5, 1.95, 5.0, 3.10, { fill: INK, border: INK });
  s.addText("산정 절차", {
    x: 0.7, y: 2.05, w: 4.6, h: 0.3, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 2,
  });
  s.addText([
    { text: "score = 100\n",  options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas", bold: true } },
    { text: "       − Σ ",    options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "VRPTW_CRITICAL × 15\n",  options: { fontSize: 13, color: RED,     fontFace: "Consolas", bold: true } },
    { text: "       − Σ ",    options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "VRPTW_WARNING  ×  5\n", options: { fontSize: 13, color: AMBER,   fontFace: "Consolas", bold: true } },
    { text: "       − ",      options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "travel_ratio_penalty\n",  options: { fontSize: 13, color: ACCENT_BG, fontFace: "Consolas" } },
    { text: "       − ",      options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "cluster_penalty   (cap −20 / day)\n", options: { fontSize: 13, color: ACCENT_BG, fontFace: "Consolas" } },
    { text: "       − ",      options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "theme_alignment_penalty\n",   options: { fontSize: 13, color: ACCENT_BG, fontFace: "Consolas" } },
    { text: "       − ",      options: { fontSize: 13, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "congestion_penalty\n\n",      options: { fontSize: 13, color: ACCENT_BG, fontFace: "Consolas" } },
    { text: "if  any CRITICAL  →  ", options: { fontSize: 12, color: PAGE_BG, fontFace: "Consolas" } },
    { text: "score = min(score, 59)", options: { fontSize: 12, color: RED, bold: true, fontFace: "Consolas" } },
  ], { x: 0.7, y: 2.40, w: 4.6, h: 2.55, margin: 0, paraSpaceAfter: 1 });

  // 우측 — 등급 + 임계
  addCard(s, 5.6, 1.95, 3.9, 1.45, { accent: true, accentColor: EMERALD });
  s.addText("등급 컷오프", {
    x: 5.8, y: 2.05, w: 3.5, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: EMERALD,
  });
  s.addText([
    { text: "PASS    ", options: { fontSize: 11, bold: true, color: EMERALD, fontFace: "Consolas" } },
    { text: "≥ 60   추천 가능\n", options: { fontSize: 11, color: TEXT } },
    { text: "REVIEW  ", options: { fontSize: 11, bold: true, color: AMBER, fontFace: "Consolas" } },
    { text: "40–59  수정 필요\n", options: { fontSize: 11, color: TEXT } },
    { text: "FAIL    ", options: { fontSize: 11, bold: true, color: RED, fontFace: "Consolas" } },
    { text: "< 40   재구성 권고", options: { fontSize: 11, color: TEXT } },
  ], { x: 5.8, y: 2.40, w: 3.5, h: 0.95, margin: 0 });

  addCard(s, 5.6, 3.50, 3.9, 1.55, { accent: true, accentColor: RED });
  s.addText("Hard Fail Cap 의 의미", {
    x: 5.8, y: 3.60, w: 3.5, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: RED,
  });
  s.addText("\"실행 불가능한 일정\"에 60점 이상이 부여될 수 없도록 시스템적으로 봉쇄. 운영시간 충돌·Depot 위반 등 결정적 결함은 자동으로 PASS 임계 미만으로 끌어내림.", {
    x: 5.8, y: 3.95, w: 3.5, h: 1.05, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: TEXT,
  });

  addFooter(s, 14);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 15 — 데이터 자산 (TourAPI + Kakao + 외부)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 05 · 데이터 자산");
  addTitle(s, "검증의 토대 — 데이터 자산", "공공 API 3종 + 자체 구축 자산 4종");

  // 4 stat cards 상단
  const stats = [
    { v: "50,234",    l: "TourAPI 수집 POI 수",            c: ACCENT },
    { v: "8 종",       l: "ContentTypeId 전 카테고리",       c: ACCENT_2 },
    { v: "322",       l: "검증 완료 장소 (큐레이션 70 일정)", c: ACCENT },
    { v: "70+",       l: "큐레이션 일정 — 17 시도 모두 포함", c: EMERALD },
  ];
  stats.forEach((st, i) => {
    const x = 0.5 + i * 2.30;
    addCard(s, x, 1.95, 2.10, 1.30, { accent: true, accentColor: st.c });
    addStat(s, x + 0.20, 2.10, 1.85, 0.95, st.v, st.l, { size: 26, color: st.c });
  });

  // 하단 좌 — 자산 상세
  addCard(s, 0.5, 3.40, 4.5, 1.65);
  s.addText("자체 구축", {
    x: 0.7, y: 3.50, w: 4.1, h: 0.28, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT, charSpacing: 1,
  });
  s.addText([
    { text: "•  pois_processed.csv  ",  options: { fontSize: 11, bold: true, color: INK, fontFace: "Consolas" } },
    { text: "주소(시도/시군구/읍면동) + 날짜 분리\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  kakao_route_cache.json  ",  options: { fontSize: 11, bold: true, color: INK, fontFace: "Consolas" } },
    { text: "양방향 캐시 — Mobility 호출 절감\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  dwell_db  ",  options: { fontSize: 11, bold: true, color: INK, fontFace: "Consolas" } },
    { text: "체류시간 5단계 폴백 (manual → lcls3 → lcls1 → contentType → default)\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  itinerary_results_*.xlsx  ",  options: { fontSize: 11, bold: true, color: INK, fontFace: "Consolas" } },
    { text: "27 컬럼 검증 출력", options: { fontSize: 10, color: TEXT } },
  ], { x: 0.7, y: 3.80, w: 4.1, h: 1.20, margin: 0, paraSpaceAfter: 1 });

  // 하단 우 — 외부 API
  addCard(s, 5.1, 3.40, 4.4, 1.65);
  s.addText("외부 API", {
    x: 5.3, y: 3.50, w: 4.0, h: 0.28, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT_2, charSpacing: 1,
  });
  s.addText([
    { text: "•  TourAPI v2 (KorService2)  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "POI 메타 + 카테고리 + 좌표 + 운영시간(detailIntro2)\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  Kakao Mobility  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "이동시간 행렬 (실측 도로망)\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  Kakao Local  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "POI 좌표 정규화 폴백\n", options: { fontSize: 10, color: TEXT } },
    { text: "•  서울 도시데이터  ",  options: { fontSize: 11, bold: true, color: INK } },
    { text: "주요 116개 관광지 5분 단위 실시간 인구", options: { fontSize: 10, color: TEXT } },
  ], { x: 5.3, y: 3.80, w: 4.0, h: 1.20, margin: 0, paraSpaceAfter: 1 });

  addFooter(s, 15);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 16 — 외부 통계/레퍼런스 (관광데이터랩 자료로 교체)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 05 · 데이터 자산 (계속)");
  addTitle(s, "정성·정량 검증 외부 레퍼런스", "한국관광공사 관광데이터랩 7종 + 통계월보");

  const refs = [
    { tag: "01", title: "2025년 국민여행조사 4분기 (잠정)",        org: "관광공사 관광데이터랩", use: "여행 횟수 · 일수 · 동선 불편 응답률", c: ACCENT },
    { tag: "02", title: "2025년 국민여행조사 3분기 (잠정)",        org: "관광공사 관광데이터랩", use: "성수기 패턴 · 지역 분포", c: ACCENT },
    { tag: "03", title: "2025 빅데이터와 함께하는 똑똑한 컨설팅 종합", org: "관광공사",            use: "관광 빅데이터 활용 사례", c: ACCENT_2 },
    { tag: "04", title: "2025 관광자원개발 및 관광투자 동향조사",    org: "관광공사",            use: "권역별 자원 분포", c: ACCENT_2 },
    { tag: "05", title: "2025 우수웰니스관광지 만족도 및 실태조사",   org: "관광공사",            use: "테마 정합성 검증 사례", c: ACCENT_2 },
    { tag: "06", title: "Data&Tourism 43호 — 방한 주요국 한국 여행 분석", org: "관광컨설팅팀",     use: "외국인 동선 인사이트", c: INK },
    { tag: "07", title: "관광 통계월보 202602",                    org: "관광공사",            use: "시군구별 월 가중치 (혼잡 폴백)", c: INK },
  ];

  refs.forEach((r, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 4.55;
    const y = 1.95 + row * 0.62;
    if (i === refs.length - 1 && col === 0) {
      // 마지막 단독 카드 (07): full width
      addCard(s, 0.5, 1.95 + row * 0.62, 9.0, 0.55, { accent: true, accentColor: r.c });
      s.addText(r.tag, {
        x: 0.7, y: y + 0.13, w: 0.5, h: 0.30, margin: 0,
        fontSize: 12, fontFace: FONT_HEADER, bold: true, color: r.c,
      });
      s.addText(r.title, {
        x: 1.2, y: y + 0.07, w: 5.6, h: 0.22, margin: 0,
        fontSize: 11, fontFace: FONT_BODY, bold: true, color: INK,
      });
      s.addText(r.org, {
        x: 1.2, y: y + 0.28, w: 5.6, h: 0.20, margin: 0,
        fontSize: 9, fontFace: FONT_BODY, italic: true, color: MUTED,
      });
      s.addText(r.use, {
        x: 7.0, y: y + 0.13, w: 2.4, h: 0.30, margin: 0,
        fontSize: 10, fontFace: FONT_BODY, color: TEXT, align: "right",
      });
      return;
    }
    addCard(s, x, y, 4.45, 0.55, { accent: true, accentColor: r.c });
    s.addText(r.tag, {
      x: x + 0.15, y: y + 0.13, w: 0.4, h: 0.30, margin: 0,
      fontSize: 12, fontFace: FONT_HEADER, bold: true, color: r.c,
    });
    s.addText(r.title, {
      x: x + 0.55, y: y + 0.05, w: 3.8, h: 0.22, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(r.org + " · " + r.use, {
      x: x + 0.55, y: y + 0.28, w: 3.8, h: 0.22, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, color: MUTED,
    });
  });

  s.addText("모든 자료는 한국관광공사 관광데이터랩(datalab.visitkorea.or.kr)에서 공식 제공 · 출처 표기 필수.", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, italic: true, color: MUTED,
  });
  addFooter(s, 16);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 17 — [D] 검증 ① Pipeline E2E
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 06 · 검증 결과 — 1 / 4");
  addTitle(s, "End-to-End 파이프라인 실행 결과", "70개 큐레이션 일정 → 322 장소 → 검증 완료");

  // 좌측 — 입력
  addCard(s, 0.5, 1.95, 4.5, 3.05);
  s.addText("입력", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT, charSpacing: 2,
  });
  s.addText("recommendations_input.xlsx", {
    x: 0.7, y: 2.35, w: 4.1, h: 0.40, margin: 0,
    fontSize: 16, fontFace: FONT_HEADER, bold: true, color: INK,
  });
  s.addText([
    { text: "•  17개 시도 모두 포함\n",                options: { fontSize: 11, color: TEXT } },
    { text: "•  ",  options: { fontSize: 11, color: TEXT } },
    { text: "당일치기 / 1박2일 / 2박3일 ", options: { fontSize: 11, bold: true, color: INK } },
    { text: "혼합\n",                                  options: { fontSize: 11, color: TEXT } },
    { text: "•  카테고리 = 관광지 · 식당 · 카페 · 시장\n", options: { fontSize: 11, color: TEXT } },
    { text: "•  AI001 ~ AI070  연속 plan_id\n",      options: { fontSize: 11, color: TEXT } },
    { text: "•  data row 총 322개 (장소 단위)",         options: { fontSize: 11, color: TEXT } },
  ], { x: 0.7, y: 2.85, w: 4.1, h: 2.10, margin: 0, paraSpaceAfter: 1 });

  // 우측 — 처리
  addCard(s, 5.10, 1.95, 4.4, 3.05, { fill: INK, border: INK });
  s.addText("처리 단계", {
    x: 5.30, y: 2.05, w: 4.0, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 2,
  });

  const steps = [
    ["1", "POI 매칭",       "TourAPI 정확/부분 매칭 + 시군구 보정"],
    ["2", "체류시간 추정",  "5단계 폴백 → 체류출처 라벨링"],
    ["3", "Kakao 행렬",     "이동시간 양방향 캐시"],
    ["4", "VRPTW 검증",    "Hard/Warning 후보 생성"],
    ["5", "Score 4종",      "travel · cluster · theme · congestion"],
    ["6", "Excel 출력",     "27 컬럼 + risk_score 포함"],
  ];
  steps.forEach((st, i) => {
    const y = 2.40 + i * 0.42;
    addNumberChip(s, 5.30, y + 0.02, st[0], ACCENT);
    s.addText(st[1], {
      x: 5.78, y, w: 1.7, h: 0.20, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: PAGE_BG,
    });
    s.addText(st[2], {
      x: 5.78, y: y + 0.20, w: 3.5, h: 0.20, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, color: SUBTLE,
    });
  });

  addFooter(s, 17);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 18 — [D] 검증 ② 매칭률 96% — 큰 stat
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 06 · 검증 결과 — 2 / 4");
  addTitle(s, "POI 매칭 정확도 — 96.0%", "공공 API 단일 소스로 90% 매칭 목표 초과 달성");

  // 거대한 stat
  s.addText("96.0%", {
    x: 0.4, y: 2.05, w: 5.4, h: 1.65, margin: 0,
    fontSize: 96, fontFace: FONT_HEADER, bold: true, color: ACCENT, align: "left",
  });
  s.addText("309 / 322 장소 매칭 성공", {
    x: 0.5, y: 3.85, w: 5.0, h: 0.30, margin: 0,
    fontSize: 14, fontFace: FONT_BODY, bold: true, color: INK,
  });
  s.addText("실패 13개 = 카페·로컬 식당 (TourAPI 미등록 자영업)", {
    x: 0.5, y: 4.15, w: 5.0, h: 0.30, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, color: MUTED,
  });

  // 우측 — 매칭 단계 분포
  addCard(s, 5.7, 1.95, 3.8, 3.05, { fill: CARD_BG });
  s.addText("매칭 단계 분포", {
    x: 5.9, y: 2.05, w: 3.4, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });

  const buckets = [
    { label: "exact",            count: 248, pct: 77.0, color: EMERALD },
    { label: "partial",           count: 41,  pct: 12.7, color: ACCENT_2 },
    { label: "partial + sigungu", count: 20,  pct:  6.2, color: ACCENT },
    { label: "not_found",         count: 13,  pct:  4.0, color: RED },
  ];
  buckets.forEach((b, i) => {
    const y = 2.45 + i * 0.62;
    s.addText(b.label, {
      x: 5.95, y, w: 1.7, h: 0.22, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: INK, fontFace: "Consolas",
    });
    // 막대
    const barW = 1.5 * (b.pct / 100) * 3.0;  // 단순 비례 (max 77%)
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.95, y: y + 0.25, w: 3.15 * (b.pct / 100) / 0.77,  // 정규화
      h: 0.18,
      fill: { color: b.color }, line: { color: b.color },
    });
    s.addText(b.pct.toFixed(1) + "%   ·   " + b.count, {
      x: 5.95, y: y + 0.45, w: 3.15, h: 0.18, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, color: MUTED,
    });
  });

  // 하단 한줄
  s.addText("실패 케이스도 match_failed.csv로 별도 출력 → 이름 보정 후 재실행 가능 (운영 가능한 매칭률 보정 루프 내장).", {
    x: 0.5, y: 5.0, w: 9.0, h: 0.25, margin: 0,
    fontSize: 10, fontFace: FONT_BODY, italic: true, color: MUTED,
  });
  addFooter(s, 18);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 19 — [D] 검증 ③ Penalty 분포
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 06 · 검증 결과 — 3 / 4");
  addTitle(s, "70 일정 검증 결과 — 등급 분포", "PASS / REVIEW / FAIL — risk_score 0–100 기준");

  // 3개 컬럼 stat
  const grades = [
    { tag: "PASS",   range: "≥ 60",  count: 47, pct: 67.1, color: EMERALD, note: "추천 가능 — Hard Fail 없음, 패널티 합 −40 이내" },
    { tag: "REVIEW", range: "40 – 59", count: 18, pct: 25.7, color: AMBER,   note: "수정 필요 — travel_ratio 또는 cluster M3+M4 발생" },
    { tag: "FAIL",   range: "< 40",  count:  5, pct:  7.2, color: RED,     note: "재구성 권고 — 운영시간 충돌 또는 Depot 위반" },
  ];
  grades.forEach((g, i) => {
    const x = 0.5 + i * 3.10;
    addCard(s, x, 1.95, 2.95, 2.20, { accent: true, accentColor: g.color });
    s.addText(g.tag, {
      x: x + 0.20, y: 2.05, w: 2.65, h: 0.30, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: g.color, charSpacing: 2,
    });
    s.addText(g.range, {
      x: x + 0.20, y: 2.32, w: 2.65, h: 0.25, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, italic: true, color: MUTED, fontFace: "Consolas",
    });
    s.addText(String(g.count), {
      x: x + 0.20, y: 2.60, w: 2.65, h: 0.85, margin: 0,
      fontSize: 56, fontFace: FONT_HEADER, bold: true, color: g.color,
    });
    s.addText(g.pct.toFixed(1) + "%   /   70 일정", {
      x: x + 0.20, y: 3.50, w: 2.65, h: 0.25, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, color: TEXT,
    });
    s.addText(g.note, {
      x: x + 0.20, y: 3.78, w: 2.65, h: 0.32, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, color: MUTED,
    });
  });

  // 하단 — 패널티 발생 분포
  addCard(s, 0.5, 4.30, 9.0, 0.85, { fill: CARD_BG });
  s.addText("패널티 발생 횟수 (70 일정 기준 · 다중 발생 허용)", {
    x: 0.7, y: 4.40, w: 8.6, h: 0.25, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT,
  });
  const occ = [
    ["Travel Ratio",  "21회"],
    ["Cluster M3",    "13회"],
    ["Cluster M4",    "9회"],
    ["Theme",          "7회"],
    ["Congestion",     "11회"],
    ["Depot 위반",     "3회"],
  ];
  occ.forEach((o, i) => {
    const x = 0.7 + i * 1.45;
    s.addText(o[0], { x, y: 4.70, w: 1.4, h: 0.22, margin: 0,
                      fontSize: 9, fontFace: FONT_BODY, color: MUTED });
    s.addText(o[1], { x, y: 4.88, w: 1.4, h: 0.22, margin: 0,
                      fontSize: 12, fontFace: FONT_HEADER, bold: true, color: INK });
  });

  addFooter(s, 19);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 20 — [D] 검증 ④ Sample Output (실제 행)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 06 · 검증 결과 — 4 / 4");
  addTitle(s, "Sample Output — 실제 검증 1행", "AI004 · 부산 1박2일 — risk_score = 47 (REVIEW)");

  // 표 — Sample row
  const COL_X = [0.5, 1.30, 1.80, 2.30, 4.20, 5.30, 6.40, 7.30, 8.30];
  const COL_W = [0.80, 0.50, 0.50, 1.90, 1.10, 1.10, 0.90, 1.00, 1.20];
  const HEADERS = ["plan_id", "day", "순서", "여행지명", "체류(분)", "이동(분)", "출처", "매칭", "risk"];
  const ROW_Y0 = 1.95;
  const ROW_H  = 0.32;
  HEADERS.forEach((h, i) => {
    s.addShape(pres.shapes.RECTANGLE, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H,
      fill: { color: INK }, line: { color: INK },
    });
    s.addText(h, {
      x: COL_X[i], y: ROW_Y0, w: COL_W[i], h: ROW_H, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, bold: true, color: PAGE_BG, align: "center", valign: "middle",
    });
  });
  const rows = [
    ["AI004","1","1","해운대해수욕장",  "120","18", "lcls3",      "exact",          ""],
    ["AI004","1","2","누리마루APEC하우스","45", "8", "lcls3",      "exact",          ""],
    ["AI004","1","3","마린시티",         "60", "12","lcls1",      "partial",        ""],
    ["AI004","1","4","광안리해수욕장",   "90", "—", "lcls3",      "exact",          ""],
    ["AI004","2","1","감천문화마을",     "75", "22","lcls3",      "exact",          ""],
    ["AI004","2","2","자갈치시장",       "60", "10","manual",      "exact",          ""],
    ["AI004","2","3","국제시장",         "45", "5", "manual",      "exact",          ""],
    ["AI004","2","4","BIFF광장",         "30", "—", "default",    "partial+sigungu",""],
  ];
  const ROW_FILLS = [CARD_BG, PAGE_BG];
  rows.forEach((r, ri) => {
    const y = ROW_Y0 + (ri + 1) * ROW_H;
    r.forEach((cell, ci) => {
      const fill = ROW_FILLS[ri % 2];
      s.addShape(pres.shapes.RECTANGLE, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H,
        fill: { color: fill }, line: { color: BORDER, width: 0.4 },
      });
      let color = TEXT;
      if (ci === 7 && cell === "exact") color = EMERALD;
      else if (ci === 7 && cell.startsWith("partial")) color = AMBER;
      else if (ci === 7 && cell === "not_found") color = RED;
      else if (ci === 6) color = ACCENT_2;
      else if (ci === 0) color = ACCENT;
      s.addText(cell, {
        x: COL_X[ci], y, w: COL_W[ci], h: ROW_H, margin: 0,
        fontSize: 9, fontFace: FONT_BODY, color, align: ci === 3 ? "left" : "center", valign: "middle",
      });
    });
  });

  // 하단 — Risk decomposition
  addCard(s, 0.5, 4.65, 9.0, 0.55, { accent: true, accentColor: AMBER });
  s.addText([
    { text: "risk_score = 47  (REVIEW)   ", options: { fontSize: 11, bold: true, color: AMBER } },
    { text: "= 100 − ", options: { fontSize: 10, color: TEXT, fontFace: "Consolas" } },
    { text: "VRPTW WARN×5(이동시간 마진 부족) ",  options: { fontSize: 10, color: AMBER, fontFace: "Consolas" } },
    { text: "− travel_ratio 16 ", options: { fontSize: 10, color: ACCENT, fontFace: "Consolas" } },
    { text: "− cluster_M3 12 ",   options: { fontSize: 10, color: ACCENT, fontFace: "Consolas" } },
    { text: "− theme 0 ",          options: { fontSize: 10, color: SUBTLE, fontFace: "Consolas" } },
    { text: "− congestion 20",      options: { fontSize: 10, color: ACCENT, fontFace: "Consolas" } },
  ], { x: 0.7, y: 4.78, w: 8.6, h: 0.32, margin: 0 });

  addFooter(s, 20);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 21 — [E] 활용 시나리오
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 07 · 활용 시나리오");
  addTitle(s, "활용 시나리오 — 누가, 어떻게 쓰는가", "B2C · B2B · 공공 3대 시장");

  const cases = [
    {
      tag: "B2C",
      title: "여행 앱의 \"검증 배지\"",
      lines: [
        "추천 일정 옆에 \"PASS · 87점\" 배지",
        "AI 일정 자동 검수로 차별화",
        "FastAPI 임베딩 — 1 호출 200ms 미만",
      ],
      color: ACCENT,
    },
    {
      tag: "B2B",
      title: "여행사 코스 운영 도구",
      lines: [
        "신규 패키지 출시 전 자동 QA",
        "Hard Fail 케이스 사전 필터",
        "Excel 27 컬럼 출력 → 운영팀 검토",
      ],
      color: ACCENT_2,
    },
    {
      tag: "공공",
      title: "지자체 관광 플랫폼",
      lines: [
        "\"권역별 추천\" 페이지 자동 검증",
        "혼잡도 기반 분산 유도 정책 반영",
        "관광데이터랩 통계와 연동",
      ],
      color: INK,
    },
  ];

  cases.forEach((c, i) => {
    const x = 0.5 + i * 3.10;
    addCard(s, x, 1.95, 2.95, 3.10, { accent: true, accentColor: c.color });
    s.addText(c.tag, {
      x: x + 0.20, y: 2.10, w: 2.65, h: 0.32, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: c.color, charSpacing: 3,
    });
    s.addText(c.title, {
      x: x + 0.20, y: 2.50, w: 2.65, h: 0.65, margin: 0,
      fontSize: 16, fontFace: FONT_HEADER, bold: true, color: INK,
    });
    c.lines.forEach((ln, li) => {
      const y = 3.30 + li * 0.50;
      addNumberChip(s, x + 0.22, y + 0.05, String(li + 1), c.color);
      s.addText(ln, {
        x: x + 0.65, y, w: 2.20, h: 0.45, margin: 0,
        fontSize: 11, fontFace: FONT_BODY, color: TEXT,
      });
    });
  });

  addFooter(s, 21);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 22 — [E] 로드맵 (운영시간 데이터 통합 명시)
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 07 · 로드맵");
  addTitle(s, "확장 로드맵", "현재 PoC → 정식 출시까지 4 단계");

  const steps = [
    {
      tag: "Now · v0.9",
      title: "PoC 완성",
      bullet: "VRPTW + 4 Scoring + Claude · 70 일정 검증 · 96% 매칭",
      color: EMERALD,
      done: true,
    },
    {
      tag: "Q3 2026",
      title: "운영시간 풀 통합",
      bullet: "TourAPI detailIntro2 usetime 50K POI 일괄 수집 → 정규식 파싱 + 신뢰도 라벨링",
      color: ACCENT,
      done: false,
    },
    {
      tag: "Q4 2026",
      title: "FastAPI 정식 서버 + Naver 폴백",
      bullet: "REST 엔드포인트 5종 · Naver 검색 폴백으로 카페·식당 매칭률 99% 목표",
      color: ACCENT_2,
      done: false,
    },
    {
      tag: "2027 H1",
      title: "Multi-modal 확장",
      bullet: "지하철/버스 환승 시간 통합 · 사진 메타로 체류시간 자동 추정",
      color: INK,
      done: false,
    },
  ];

  steps.forEach((st, i) => {
    const y = 2.0 + i * 0.78;
    addCard(s, 0.5, y, 9.0, 0.65, { accent: true, accentColor: st.color });
    s.addText(st.tag, {
      x: 0.7, y: y + 0.10, w: 1.6, h: 0.30, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: st.color, charSpacing: 1,
    });
    s.addText(st.done ? "✓" : String(i + 1), {
      x: 2.4, y: y + 0.13, w: 0.3, h: 0.30, margin: 0,
      fontSize: 14, fontFace: FONT_HEADER, bold: true, color: st.color, align: "center",
    });
    s.addText(st.title, {
      x: 2.8, y: y + 0.07, w: 6.5, h: 0.28, margin: 0,
      fontSize: 13, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(st.bullet, {
      x: 2.8, y: y + 0.34, w: 6.5, h: 0.28, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: TEXT,
    });
  });

  s.addText("운영시간 데이터  →  TourAPI detailIntro2 의 usetime 필드 (예: \"09:00~18:00(입장마감 17:00)\")  ·  일일 10K 호출 한도, 50K POI는 약 5일 분할 수집.", {
    x: 0.5, y: 5.05, w: 9.0, h: 0.22, margin: 0,
    fontSize: 9, fontFace: FONT_BODY, italic: true, color: MUTED,
  });
  addFooter(s, 22);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 23 — 한계 + 강점 요약
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: PAGE_BG };
  addPageHeader(s, "Section 08 · 한계 · 강점");
  addTitle(s, "정직한 한계 + 차별화된 강점", "Limitations & Strengths");

  // 좌 — 한계
  addCard(s, 0.5, 1.95, 4.5, 3.10, { accent: true, accentColor: AMBER });
  s.addText("현재의 한계", {
    x: 0.7, y: 2.05, w: 4.1, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: AMBER, charSpacing: 2,
  });
  const limits = [
    ["카페·로컬 식당",     "TourAPI 미등록 케이스 4% 매칭 실패"],
    ["운영시간 일괄 적재", "현재는 표본만, 50K 전수 수집은 로드맵"],
    ["LLM 비용",            "테마 정합성 호출당 ~$0.0003, 캐싱으로 완화"],
    ["서울 외 실시간 혼잡", "API 미제공 → 계절성 폴백 의존"],
  ];
  limits.forEach((l, i) => {
    const y = 2.45 + i * 0.62;
    s.addText(l[0], {
      x: 0.7, y, w: 4.1, h: 0.25, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: INK,
    });
    s.addText(l[1], {
      x: 0.7, y: y + 0.25, w: 4.1, h: 0.30, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: MUTED,
    });
  });

  // 우 — 강점
  addCard(s, 5.10, 1.95, 4.4, 3.10, { fill: INK, border: INK });
  s.addText("차별화된 강점", {
    x: 5.30, y: 2.05, w: 4.0, h: 0.30, margin: 0,
    fontSize: 12, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 2,
  });
  const strengths = [
    ["검증 레이어",          "기존 추천 서비스가 비워둔 시장 공백을 정조준"],
    ["Hybrid 결합",         "Rule(VRPTW) + Score(4종) + LLM(설명) 단일 파이프라인"],
    ["설명 가능성",          "모든 판정이 fact·rule·suggestion 으로 추적 가능"],
    ["공공 데이터 우선",      "TourAPI · Kakao · 서울 도시데이터 + 관광데이터랩 통계"],
    ["실측 매칭률",          "70 일정 322 장소 96% 매칭 — 운영 가능 수준"],
  ];
  strengths.forEach((st, i) => {
    const y = 2.42 + i * 0.50;
    s.addText("✓", {
      x: 5.30, y, w: 0.30, h: 0.25, margin: 0,
      fontSize: 13, fontFace: FONT_HEADER, bold: true, color: ACCENT_BG,
    });
    s.addText(st[0], {
      x: 5.65, y, w: 3.6, h: 0.22, margin: 0,
      fontSize: 11, fontFace: FONT_BODY, bold: true, color: PAGE_BG,
    });
    s.addText(st[1], {
      x: 5.65, y: y + 0.22, w: 3.6, h: 0.25, margin: 0,
      fontSize: 9, fontFace: FONT_BODY, color: SUBTLE,
    });
  });

  addFooter(s, 23);
}

// ═══════════════════════════════════════════════════════════════
// SLIDE 24 — 레퍼런스 / 마무리
// ═══════════════════════════════════════════════════════════════
{
  let s = pres.addSlide();
  s.background = { color: DARK_BG };

  // 좌상단 액센트
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 0.7, w: 0.04, h: 0.36,
    fill: { color: ACCENT }, line: { color: ACCENT },
  });
  s.addText("References & Acknowledgements", {
    x: 0.85, y: 0.7, w: 8.4, h: 0.36, margin: 0,
    fontSize: 11, fontFace: FONT_BODY, bold: true, color: ACCENT_BG, charSpacing: 3,
  });

  s.addText("References", {
    x: 0.7, y: 1.30, w: 8.6, h: 0.5, margin: 0,
    fontSize: 32, fontFace: FONT_HEADER, bold: true, color: PAGE_BG,
  });

  const refs = [
    ["1.", "한국관광공사 관광데이터랩 — 2025년 국민여행조사 3·4분기 결과(잠정치)"],
    ["2.", "한국관광공사 — 2025 빅데이터와 함께하는 똑똑한 컨설팅 종합보고서"],
    ["3.", "한국관광공사 — 2025 관광자원개발 및 관광투자 동향조사 분석 최종보고서"],
    ["4.", "한국관광공사 — 2025 우수웰니스관광지 만족도 및 실태조사"],
    ["5.", "관광컨설팅팀 — Data&Tourism 43호: 소셜 데이터 기반 방한 주요국 한국 여행 분석"],
    ["6.", "한국관광공사 — 관광 통계월보 (202602)"],
    ["7.", "Solomon, M.M. (1987). Algorithms for the Vehicle Routing and Scheduling Problems with Time Window Constraints. Operations Research, 35(2): 254–265."],
    ["8.", "TourAPI v2 (KorService2) · Kakao Mobility API · 서울특별시 실시간 도시데이터"],
    ["9.", "Anthropic Claude Sonnet 4.6 · Google OR-Tools (constraint_solver)"],
  ];
  refs.forEach((r, i) => {
    const y = 2.05 + i * 0.32;
    s.addText(r[0], {
      x: 0.7, y, w: 0.4, h: 0.28, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, bold: true, color: ACCENT,
    });
    s.addText(r[1], {
      x: 1.1, y, w: 8.4, h: 0.28, margin: 0,
      fontSize: 10, fontFace: FONT_BODY, color: ACCENT_BG,
    });
  });

  // 마무리 카피
  s.addText("Thank you.", {
    x: 0.7, y: 5.0, w: 5.0, h: 0.4, margin: 0,
    fontSize: 18, fontFace: FONT_HEADER, italic: true, color: PAGE_BG,
  });
  s.addText("이건상  ·  2026.05.02", {
    x: 5.5, y: 5.05, w: 3.8, h: 0.3, margin: 0,
    fontSize: 10, fontFace: FONT_BODY, color: SUBTLE, align: "right",
  });
}

// ═══════════════════════════════════════════════════════════════
// 저장
// ═══════════════════════════════════════════════════════════════
const OUTPUT = path.join(__dirname, "..", "data", "Travel_QA_Engine_2026.pptx");
pres.writeFile({ fileName: OUTPUT }).then(fn => {
  console.log("[OK] PPT 생성 완료:", fn);
});
