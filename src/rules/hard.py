# -*- coding: utf-8 -*-
"""
하드 제약 — 하나라도 걸리면 그 자리에 그 레시피를 넣지 않는다.

§4 주재료/조리 중복, §4-3 월간 상한, §4-4 김치 회피,
§5 로테이션, §6 요일 고정, §7-1 알레르기 상한,
그리고 src.rules.combination 의 hard 룰.
"""
from __future__ import annotations

import datetime
from typing import Dict, Optional

from src.config.constants import (
    ALLERGY_DAILY_MAX,
    DONBURI_MAX,
    FAVORITE_SUB2,
    GIM_MONTHLY,
    PRIORITY_ALLERGY,
    READY_MAIN_MAX,
    ROTATION,
    SALAD_ROTATION,
    SEAWEED_WEEKLY_MAX,
    SOUP_FAV_MONTHLY_MAX,
    SOUP_FAVORITES,
)
from src.rules import combination
from src.rules.pools import is_donburi, is_salad


def _recipes_of(repo, day: Dict[str, str]) -> Dict[str, object]:
    return {s: repo.recipes[r] for s, r in day.items()
            if r and not s.startswith("_") and r in repo.recipes}


def violates(repo, state, d: datetime.date, day: Dict[str, str],
             slot: str, rid: str, line: str = "유아") -> Optional[str]:
    """위반 사유 문자열 또는 None."""
    r = repo.recipes[rid]

    # --- 같은 날 동일 레시피 ---
    if rid in day.values():
        return "같은 날 중복"

    day_recipes = _recipes_of(repo, day)

    # --- §4-1 주재료 중복 (밥·김치 제외) ---
    if slot in ("메인", "서브1", "서브2", "국") and r.proteins:
        for s2, r2 in day_recipes.items():
            if s2 in ("밥", "김치"):
                continue
            shared = r.proteins & r2.proteins
            if shared:
                return f"주재료 중복({','.join(sorted(shared))}) ↔ {r2.rep}"

    # --- §4-2 튀김 2개 금지 ---
    if r.cook == "튀김" and any(r2.cook == "튀김" for r2 in day_recipes.values()):
        return "튀김 2개"

    # --- 조합 기피 룰 (통계 근거) ---
    combo = combination.check_hard(repo, day_recipes, slot, r, line)
    if combo:
        return combo

    # --- §4-3 월간 상한 ---
    if slot == "메인":
        if r.ready and state.ready_main >= READY_MAIN_MAX:
            return f"완조리 메인 월 상한({READY_MAIN_MAX})"
        if is_donburi(r) and state.donburi >= DONBURI_MAX:
            return f"덮밥소스류 월 상한({DONBURI_MAX})"

    # --- §4-4 김치 재료 회피 ---
    if slot == "김치":
        for r2 in day_recipes.values():
            n2 = r2.rep
            if r.rep == "깍두기" and "깍두기" in n2:
                return "깍두기 재료 중복"
            if r.rep == "배추김치" and "김치" in n2 and "깍두기" not in n2:
                return "김치 재료 중복"
            if r.rep == "열무김치" and "열무" in n2:
                return "열무 재료 중복"

    # --- §7-1 최우선 알레르기 하루 상한 ---
    for n in r.allergy_codes & set(PRIORITY_ALLERGY):
        cnt = sum(1 for r2 in day_recipes.values() if n in r2.allergy_codes)
        if cnt >= ALLERGY_DAILY_MAX:
            return f"최우선 알레르기 {n}번 하루 {ALLERGY_DAILY_MAX}개 초과"

    # --- §6 도시락김류: 금요일만, 월 GIM_MONTHLY 회 ---
    if any(f in r.rep for f in FAVORITE_SUB2):
        if d.weekday() != 4:
            return "도시락김류는 금요일만 편성"
        used = sum(c for rid2, c in state.month_use.items()
                   if rid2 in repo.recipes
                   and any(f in repo[rid2].rep for f in FAVORITE_SUB2))
        if used >= GIM_MONTHLY:
            return f"도시락김류 월 상한({GIM_MONTHLY})"

    # --- §5 로테이션 ---
    lo, hi = ROTATION[slot]
    if is_salad(r) and slot in ("서브1", "서브2"):
        lo, hi = SALAD_ROTATION
    gap = state.gap(rid, d)

    if slot == "국":
        if r.rep in SOUP_FAVORITES:
            if state.month_use[rid] >= SOUP_FAV_MONTHLY_MAX:
                return f"선호국 월 상한({SOUP_FAV_MONTHLY_MAX})"
        elif gap < lo:
            return f"로테이션 미달({gap}일 < {lo}일)"
        if "미역국" in r.rep:
            n = sum(1 for x in state.week_days(d)
                    for r2 in state.days[x].values()
                    if r2 in repo.recipes and "미역국" in repo[r2].rep)
            if n >= SEAWEED_WEEKLY_MAX:
                return "미역국 주 1회 초과"
    elif slot in ("메인", "서브1", "서브2"):
        if gap < lo:
            return f"로테이션 미달({gap}일 < {lo}일)"

    return None
