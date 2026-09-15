# -*- coding: utf-8 -*-
"""
조합 분석 — 1년치 실제 식단표에서 '나오지 않은 패턴'을 찾는다.

핵심: 교차표의 빈칸은 두 가지 이유로 생긴다.
  (a) 실제로 피하는 조합    → 룰로 승격할 가치가 있다
  (b) 단순히 표본이 적어서   → 룰로 만들면 과적합이다
둘을 가르기 위해 독립가정 기대값 e = P(A)·P(B)·N 을 계산하고,
관측 0회가 우연일 확률 P(0|e) = exp(-e) 를 함께 보고한다.
P < 0.05 인 빈칸만 '기피 후보'로 본다.
"""
from __future__ import annotations

import collections
import json
import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from src.rules.combination import soup_category

ALPHA = 0.05          # 유의수준
MIN_EXPECT = 3.0      # 이보다 기대값이 작으면 표본 부족으로 판단 보류
SPARSE_RATIO = 3.0    # 관측 <= 기대/3 이면 '희소'로 별도 보고


@dataclass
class CellResult:
    a: str
    b: str
    observed: int
    expected: float
    p_zero: float

    @property
    def verdict(self) -> str:
        if self.observed == 0 and self.expected >= MIN_EXPECT and self.p_zero < ALPHA:
            return "기피"
        if self.observed == 0:
            return "표본부족"
        if self.expected >= 5 and self.observed <= self.expected / SPARSE_RATIO:
            return "희소"
        return "정상"


# ======================================================================
# 일자별 특징 추출
# ======================================================================
def day_features(repo, days_json_path) -> List[dict]:
    """days.json(일자→슬롯별 recipe_id) → 분석용 특징 레코드."""
    raw = json.loads(open(days_json_path, encoding="utf-8").read())
    rows = []
    for d in raw:
        slots = d["slots"]
        soups = [repo[r] for r in slots.get("국", []) if r in repo.recipes]
        mains = [repo[r] for r in slots.get("메인", []) if r in repo.recipes]
        subs = [repo[r] for r in slots.get("서브", []) if r in repo.recipes]
        rices = [repo[r] for r in slots.get("밥", []) if r in repo.recipes]
        if not soups or not mains:
            continue
        g, mn = soups[0], mains[0]
        rows.append({
            "date": d["date"],
            "rice": rices[0].rep if rices else "",
            "soup_name": g.rep,
            "soup_cat": soup_category(g),
            "soup_protein": (g.protein.split(",")[0].strip() if g.protein else ""),
            "main_name": mn.rep,
            "main_cook": mn.cook,
            "main_protein": (mn.protein.split(",")[0].strip() if mn.protein else ""),
            "main_ready": mn.ready,
            "sub_cooks": [s.cook for s in subs if s.cook],
            "sub_proteins": [s.protein.split(",")[0].strip() for s in subs if s.protein],
        })
    return rows


# ======================================================================
# 교차표
# ======================================================================
def crosstab(rows: Sequence[dict], key_a: str, key_b: str) -> List[CellResult]:
    """key 가 list 인 축은 '그 날 등장한 값들'로 펼쳐 센다."""
    A: collections.Counter = collections.Counter()
    B: collections.Counter = collections.Counter()
    C: collections.Counter = collections.Counter()
    n = 0
    for r in rows:
        av = r[key_a]
        avs = sorted(set(av)) if isinstance(av, list) else ([av] if av else [])
        bv = r[key_b]
        bvs = sorted(set(bv)) if isinstance(bv, list) else ([bv] if bv else [])
        avs = [x for x in avs if x != ""]
        bvs = [x for x in bvs if x != ""]
        if not avs or not bvs:
            continue
        n += 1
        for a in avs:
            A[a] += 1
        for b in bvs:
            B[b] += 1
        for a in avs:
            for b in bvs:
                C[(a, b)] += 1
    out = []
    for a in A:
        for b in B:
            e = A[a] * B[b] / n if n else 0.0
            o = C.get((a, b), 0)
            out.append(CellResult(a, b, o, e, math.exp(-e)))
    return out


def self_pairs(rows: Sequence[dict], key: str) -> List[CellResult]:
    """같은 날 같은 축의 값끼리 동시 등장(예: 서브 조리방식 두 개)."""
    single: collections.Counter = collections.Counter()
    pair: collections.Counter = collections.Counter()
    n = 0
    for r in rows:
        vals = sorted({v for v in r[key] if v})
        if not vals:
            continue
        n += 1
        for v in vals:
            single[v] += 1
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                pair[(vals[i], vals[j])] += 1
    keys = sorted(single)
    out = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = keys[i], keys[j]
            e = single[a] * single[b] / n if n else 0.0
            o = pair.get((a, b), 0)
            out.append(CellResult(a, b, o, e, math.exp(-e)))
    return out


# ======================================================================
# 리포트
# ======================================================================
AXES = [
    ("밥 × 국", "rice", "soup_name", crosstab),
    ("밥 × 국 범주", "rice", "soup_cat", crosstab),
    ("국 범주 × 메인 조리방식", "soup_cat", "main_cook", crosstab),
    ("국 범주 × 메인 단백질", "soup_cat", "main_protein", crosstab),
    ("국 단백질 × 메인 단백질", "soup_protein", "main_protein", crosstab),
    ("국 범주 × 서브 조리방식", "soup_cat", "sub_cooks", crosstab),
    ("메인 조리 × 서브 조리", "main_cook", "sub_cooks", crosstab),
    ("서브 조리 × 서브 조리(같은 날)", "sub_cooks", None, self_pairs),
]


def report(rows: Sequence[dict]) -> str:
    lines = [f"# 조합 분석 — 분석 대상 {len(rows)}영업일", ""]
    for title, ka, kb, fn in AXES:
        cells = fn(rows, ka) if kb is None else fn(rows, ka, kb)
        avoid = sorted([c for c in cells if c.verdict == "기피"],
                       key=lambda c: -c.expected)
        sparse = sorted([c for c in cells if c.verdict == "희소"],
                        key=lambda c: c.observed / max(c.expected, 1e-9))
        empty = sum(1 for c in cells if c.observed == 0)
        lines.append(f"## {title}")
        lines.append(f"- 전체 셀 {len(cells)} / 빈 셀 {empty} / "
                     f"기피 후보 {len(avoid)} / 희소 {len(sparse)}")
        if not avoid and not sparse:
            lines.append("- 통계적으로 의미 있는 기피 조합 없음 (빈칸은 표본 부족)")
        for c in avoid:
            lines.append(f"  - **[0회] {c.a} × {c.b}** — 기대 {c.expected:.1f}회, "
                         f"우연일 확률 {c.p_zero:.3f}")
        for c in sparse:
            lines.append(f"  - [희소] {c.a} × {c.b} — 관측 {c.observed}회 / "
                         f"기대 {c.expected:.1f}회")
        lines.append("")
    return "\n".join(lines)
