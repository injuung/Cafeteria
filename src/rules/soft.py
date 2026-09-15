# -*- coding: utf-8 -*-
"""점수 함수 — 하드 제약을 통과한 후보들 사이의 우선순위."""
from __future__ import annotations

import datetime
from typing import Dict

from src.config.constants import (
    FAVORITE_SUB2,
    READY_MAIN_TARGET,
    ROTATION,
    SALAD_ROTATION,
    WEIGHT,
)
from src.rules import combination
from src.rules.pools import is_salad


def _recipes_of(repo, day: Dict[str, str]):
    return {s: repo.recipes[r] for s, r in day.items()
            if r and not s.startswith("_") and r in repo.recipes}


def score(repo, state, d: datetime.date, day: Dict[str, str],
          slot: str, rid: str, line: str = "유아") -> float:
    r = repo.recipes[rid]
    day_recipes = _recipes_of(repo, day)
    s = 0.0

    # --- 로테이션 목표 근접도 ---
    lo, hi = ROTATION[slot]
    if is_salad(r) and slot in ("서브1", "서브2"):
        lo, hi = SALAD_ROTATION
    gap = min(state.gap(rid, d), 400)
    if gap >= hi:
        s += WEIGHT["gap_fit"] * min(1.0, (gap - hi) / 120 + 1.0)
    else:
        s += WEIGHT["gap_fit"] * max(0.0, (gap - lo) / max(1, hi - lo))

    # --- 같은 날 조리방식 중복 ---
    s += WEIGHT["cook_repeat"] * sum(1 for r2 in day_recipes.values() if r2.cook == r.cook)

    # --- 같은 주 조리방식·단백질 반복 ---
    week = [state.days[x] for x in state.week_days(d)]
    ck = sum(1 for dd in week for r2 in dd.values()
             if r2 in repo.recipes and repo[r2].cook == r.cook)
    s += WEIGHT["cook_week"] * min(ck, 4) / 4
    if r.proteins:
        pk = sum(1 for dd in week for r2 in dd.values()
                 if r2 in repo.recipes and (repo[r2].proteins & r.proteins))
        s += WEIGHT["protein_week"] * min(pk, 5) / 5

    # --- §5-1 완조리·닭 메인인 날 소고기 국 가점 ---
    if slot == "국":
        main = day.get("메인")
        if main in repo.recipes:
            mm = repo[main]
            if (mm.ready or "계육" in mm.protein) and "우육" in r.protein:
                s += WEIGHT["beef_soup"]
        if "미역국" in r.rep:
            n = sum(1 for dd in week for r2 in dd.values()
                    if r2 in repo.recipes and "미역국" in repo[r2].rep)
            if n == 0:
                s += WEIGHT["seaweed_weekly"]

    # --- 완조리 메인: 목표까지는 중립, 넘어서면 억제 ---
    if slot == "메인" and r.ready and state.ready_main >= READY_MAIN_TARGET:
        s += WEIGHT["ready_penalty"] * (1 + state.ready_main - READY_MAIN_TARGET)

    # --- 선호 서브2 ---
    if slot == "서브2" and any(f in r.rep for f in FAVORITE_SUB2):
        s += WEIGHT["favorite"]

    # --- 과거 사용빈도 prior ---
    s += WEIGHT["freq_prior"] * min(state.freq.get(rid, 0), 20) / 20

    # --- 조합 기피 룰(soft) 감점 ---
    s += WEIGHT["combo_penalty"] * combination.count_soft(repo, day_recipes, slot, r, line)

    return s
