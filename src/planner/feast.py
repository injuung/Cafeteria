# -*- coding: utf-8 -*-
"""생일파티 특식 구성 — 국 없음, 김치 대신 피클, 디저트 추가.
   단 1·2·8월은 국·김치를 함께 낸다(담당자 확정)."""
from __future__ import annotations

import datetime
from typing import Dict, Tuple

from src.config.constants import (
    FEAST_ROTATION_DAYS,
    FEAST_WITH_SOUP_MONTHS,
    TOP_N,
)
from src.rules.hard import violates
from src.rules.soft import score

FEAST_TEMPLATE = {
    "밥": ["소고기볶음밥", "버터계란볶음밥", "햄채소볶음밥", "김가루밥"],
    "메인": ["스파게티면"],
    "서브1": ["눈꽃치즈치킨", "순살치킨", "용가리치킨너겟", "치킨가라아게", "뿌링클치킨"],
    "서브2": ["캐릭터찐빵", "과일샐러드", "카프레제샐러드"],
    "김치": ["수제피클"],
}
FEAST_DESSERT = ["딸기짜요", "젤리스틱포도"]


def pick_feast(repo, state, d: datetime.date, pools=None,
               line: str = "유아") -> Tuple[Dict[str, str], Dict[str, str]]:
    day: Dict[str, str] = {}
    why: Dict[str, str] = {}
    with_soup = d.month in FEAST_WITH_SOUP_MONTHS

    for slot, names in FEAST_TEMPLATE.items():
        if with_soup and slot == "김치":
            continue                       # 1·2·8월은 피클 대신 실제 김치
        best, best_gap = None, -1
        for nm in names:
            rid = repo.rid_by_rep.get(nm)
            if not rid or rid in day.values():
                continue
            g = state.gap(rid, d)
            if g > best_gap:
                best, best_gap = rid, g
        if best:
            day[slot] = best
            tag = "미출현" if best_gap >= 9999 else (
                "3개월 경과" if best_gap >= FEAST_ROTATION_DAYS else f"직전 {best_gap}일")
            why[slot] = f"생일파티 특식 · {tag}"

    if with_soup and pools:
        for slot in ("국", "김치"):
            cands = []
            for rid, _ in pools[slot]:
                if violates(repo, state, d, day, slot, rid, line):
                    continue
                cands.append((score(repo, state, d, day, slot, rid, line), rid))
                if len(cands) >= TOP_N:
                    break
            if cands:
                cands.sort(reverse=True)
                day[slot] = cands[0][1]
                why[slot] = f"{d.month}월 특식일 — 국·김치 제공 (담당자 확정)"
    return day, why
