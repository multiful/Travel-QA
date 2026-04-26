"""
AI 여행 추천 성능 시각화 — 프로젝트 필요성 근거 차트 4종
"""
import json, sys
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path
from collections import defaultdict

matplotlib.rcParams['font.family'] = ['Malgun Gothic', 'AppleGothic', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False

BASE    = Path(__file__).resolve().parent
data    = json.loads((BASE / "analysis_result.json").read_text(encoding="utf-8"))
entries = data["entries"]

tr_all  = [e["travel_ratio"] for e in entries if e["travel_ratio"] is not None]
dur_map = {"당일여행": [], "1박 2일": [], "2박 3일": []}
for e in entries:
    if e["travel_ratio"] is not None:
        dur_map[e["duration"]].append(e["travel_ratio"])

# ── 색상 팔레트 ───────────────────────────────────────────────────────────
C_OK   = "#4CAF50"   # 정상
C_WARN = "#FF9800"   # 경고
C_CRIT = "#F44336"   # 위험
C_BG   = "#FAFAFA"

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.patch.set_facecolor(C_BG)
fig.suptitle(
    "AI 여행 추천 품질 분석 — 대한민국 구석구석 50개 일정 (101 day)",
    fontsize=15, fontweight="bold", y=0.98
)

# ── Chart 1: 이동 비율 분포 히스토그램 ──────────────────────────────────
ax1 = axes[0, 0]
ax1.set_facecolor(C_BG)

bins = np.arange(0, 0.82, 0.04)
colors = []
for b in bins[:-1]:
    if b < 0.20:
        colors.append(C_OK)
    elif b < 0.40:
        colors.append(C_WARN)
    else:
        colors.append(C_CRIT)

n, bin_edges, patches = ax1.hist(tr_all, bins=bins, edgecolor="white", linewidth=0.8)
for patch, color in zip(patches, colors):
    patch.set_facecolor(color)

ax1.axvline(0.20, color=C_WARN, linestyle="--", linewidth=1.5, label="경고 기준 (20%)")
ax1.axvline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, label="위험 기준 (40%)")
ax1.set_xlabel("이동 비율 (travel_ratio)", fontsize=11)
ax1.set_ylabel("일정 수 (day)", fontsize=11)
ax1.set_title("① 이동 비율 분포\n공식 추천에도 이동에 과다 시간 소비", fontsize=11, fontweight="bold")
ax1.legend(fontsize=9)

normal_n = sum(1 for v in tr_all if v < 0.20)
warn_n   = sum(1 for v in tr_all if 0.20 <= v < 0.40)
crit_n   = sum(1 for v in tr_all if v >= 0.40)
ax1.text(0.62, max(n) * 0.75,
    f"정상  {normal_n}건 (83.2%)\n경고  {warn_n}건 (5.0%)\n위험  {crit_n}건 (11.9%)",
    fontsize=9, bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))

# ── Chart 2: 기간 유형별 박스플롯 ────────────────────────────────────────
ax2 = axes[0, 1]
ax2.set_facecolor(C_BG)

labels = ["당일여행", "1박 2일", "2박 3일"]
box_data = [dur_map[d] for d in labels]
bp = ax2.boxplot(box_data, labels=labels, patch_artist=True,
                 medianprops=dict(color="black", linewidth=2),
                 whiskerprops=dict(linewidth=1.5),
                 flierprops=dict(marker="o", markersize=5, alpha=0.6))

box_colors = [C_WARN, C_OK, C_CRIT]
for patch, color in zip(bp["boxes"], box_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

ax2.axhline(0.20, color=C_WARN, linestyle="--", linewidth=1.5, alpha=0.8)
ax2.axhline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, alpha=0.8)
ax2.set_ylabel("이동 비율", fontsize=11)
ax2.set_title("② 여행 기간별 이동 비율\n2박3일 일정의 분산이 가장 심각", fontsize=11, fontweight="bold")

means = [np.mean(d) for d in box_data]
for i, (m, d) in enumerate(zip(means, box_data)):
    crit = sum(1 for v in d if v >= 0.40)
    ax2.text(i+1.18, m, f"평균\n{m:.2f}", fontsize=8, va="center", color="navy")

# ── Chart 3: 파이차트 — 전체 일정 품질 판정 ─────────────────────────────
ax3 = axes[1, 0]
ax3.set_facecolor(C_BG)

sizes  = [normal_n, warn_n, crit_n]
clrs   = [C_OK, C_WARN, C_CRIT]
explode = (0, 0.05, 0.10)
wedges, texts, autotexts = ax3.pie(
    sizes, labels=None, colors=clrs, explode=explode,
    autopct="%1.1f%%", startangle=90,
    pctdistance=0.75, textprops=dict(fontsize=11)
)
for at in autotexts:
    at.set_fontweight("bold")

legend_labels = [
    f"정상 (이동 < 20%)   {normal_n}건",
    f"경고 (20~40%)      {warn_n}건",
    f"위험 (이동 ≥ 40%)   {crit_n}건",
]
ax3.legend(wedges, legend_labels, loc="lower center",
           bbox_to_anchor=(0.5, -0.12), fontsize=9)
ax3.set_title("③ AI 추천 일정 품질 판정\n1/6은 경고 이상 — 검증 레이어 필요", fontsize=11, fontweight="bold")

# ── Chart 4: 심각 사례 산점도 (이동비율 vs 최대거리) ─────────────────────
ax4 = axes[1, 1]
ax4.set_facecolor(C_BG)

dist_clip = 320  # 시각화 클립값
xs, ys, cs, labels_pt = [], [], [], []
for e in entries:
    if e["travel_ratio"] is None:
        continue
    d = min(e["max_dist_km"], dist_clip)
    xs.append(d)
    ys.append(e["travel_ratio"])
    if e["travel_ratio"] >= 0.40:
        cs.append(C_CRIT)
    elif e["travel_ratio"] >= 0.20:
        cs.append(C_WARN)
    else:
        cs.append(C_OK)

ax4.scatter(xs, ys, c=cs, alpha=0.65, edgecolors="white", linewidth=0.5, s=55)
ax4.axhline(0.40, color=C_CRIT, linestyle="--", linewidth=1.5, label="위험 기준 (40%)")
ax4.axhline(0.20, color=C_WARN, linestyle="--", linewidth=1.2, alpha=0.7, label="경고 기준 (20%)")
ax4.axvline(50,   color="gray",  linestyle=":",  linewidth=1.2, alpha=0.7, label="광역 이탈 (50km)")

# 최악 사례 레이블
worst = sorted(
    [(e["num"], e["region"], e["duration"], min(e["max_dist_km"], dist_clip), e["travel_ratio"])
     for e in entries if e["travel_ratio"] and e["travel_ratio"] >= 0.45],
    key=lambda x: -x[4]
)[:5]
for num, region, dur, d, tr in worst:
    ax4.annotate(f"#{num} {region}", xy=(d, tr),
                 xytext=(d + 4, tr + 0.01), fontsize=7.5,
                 arrowprops=dict(arrowstyle="->", lw=0.8))

ax4.set_xlabel("같은 날 POI 최대 직선거리 (km)", fontsize=11)
ax4.set_ylabel("이동 비율", fontsize=11)
ax4.set_title("④ 지리 분산 vs 이동 비율\nAI가 먼 도시 장소를 같은 날 배치", fontsize=11, fontweight="bold")
ax4.legend(fontsize=8)

patches_leg = [
    mpatches.Patch(color=C_OK,   label="정상"),
    mpatches.Patch(color=C_WARN, label="경고"),
    mpatches.Patch(color=C_CRIT, label="위험"),
]
ax4.legend(handles=patches_leg, fontsize=8, loc="upper left")

plt.tight_layout(rect=[0, 0, 1, 0.96])
out = BASE / "ai_travel_quality_report.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=C_BG)
plt.close()
print(f"저장 완료: {out}")
