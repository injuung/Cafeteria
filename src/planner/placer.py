# -*- coding: utf-8 -*-
"""배치기 — 하루 6칸을 우선순위 순서로 채운다."""
from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple

from src.config.constants import PLACE_ORDER, TOP_N
from src.domain.models import DayPlan, MonthPlan
from src.planner.calendar import feast_days, gim_days
from src.planner.feast import FEAST_DESSERT, pick_feast
from src.rules.hard import violates
from src.rules.pools import build_pools
from src.rules.soft import score
from src.rules.state import PlacementState


def place_day(repo, state, d: datetime.date, pools,
              forced: Optional[Dict[str, str]] = None,
              line: str = "유아"
              ) -> Tuple[Optional[Tuple[Dict[str, str], Dict[str, str]]], Optional[str]]:
    day: Dict[str, str] = {}
    why: Dict[str, str] = {}
    for slot, rid in (forced or {}).items():
        day[slot] = rid
        why[slot] = "캘린더 고정 규칙"

    for slot in PLACE_ORDER:
        if slot in day:
            continue
        cands: List[Tuple[float, str]] = []
        for rid, _ in pools[slot]:
            if violates(repo, state, d, day, slot, rid, line):
                continue
            cands.append((score(repo, state, d, day, slot, rid, line), rid))
            if len(cands) >= TOP_N * 3:
                break
        if not cands:
            return None, f"{slot} 칸 후보 없음"
        cands.sort(reverse=True)
        sc, rid = cands[0]
        day[slot] = rid
        r = repo[rid]
        g = state.gap(rid, d)
        why[slot] = (f"직전 {g if g < 9999 else '미출현'}일 · "
                     f"{r.protein or '-'} · {r.cook} · 알레{r.allergy} · 점수 {sc:.2f}")
    return (day, why), None


def generate_month(repo, year: int, month: int,
                   days: Optional[List[datetime.date]] = None,
                   blacklist=(), line: str = "유아") -> MonthPlan:
    ym = f"{year:04d}-{month:02d}"
    cut = f"{ym}-01"
    if days is None:
        days = repo.business_days(ym, line)
    days = sorted(days)

    state = PlacementState(repo, cut, line)
    pools = build_pools(repo, blacklist, line)

    feast = feast_days(days)
    gim = gim_days(days, feast)
    gim_rid = repo.rid_by_rep.get("도시락김")

    plan = MonthPlan(year=year, month=month, line=line)

    for d in days:
        if d in feast:
            slots, why = pick_feast(repo, state, d, pools, line)
            state.commit(d, slots)
            dp = DayPlan(date=d, slots=slots, reasons=why, is_feast=True)
            dp.dessert = FEAST_DESSERT[len(plan.days) % len(FEAST_DESSERT)]
            plan.days[d] = dp
            continue

        forced = {}
        if d in gim and gim_rid:
            forced["서브2"] = gim_rid
        res, err = place_day(repo, state, d, pools, forced, line)
        if res is None and forced:
            res, err = place_day(repo, state, d, pools, {}, line)   # 고정 해제 후 재시도
        if res is None:
            plan.failures.append((d, err))
            continue
        slots, why = res
        state.commit(d, slots)
        plan.days[d] = DayPlan(date=d, slots=slots, reasons=why)

    return plan, state
