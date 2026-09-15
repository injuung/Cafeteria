# -*- coding: utf-8 -*-
"""
MonthPlan(도메인 모델) → 엑셀 출력기가 기대하는 평면 dict 로 변환.

출력기는 서식 코드가 대부분이라 도메인 모델을 직접 알 필요가 없다.
경계를 이 파일 하나로 좁혀 둔다.
"""
from __future__ import annotations

import datetime
from typing import Dict, Tuple

from src.domain.models import MonthPlan

PlanDict = Dict[datetime.date, Dict[str, str]]
NoteDict = Dict[datetime.date, Dict[str, str]]


def flatten(plan: MonthPlan) -> Tuple[PlanDict, NoteDict]:
    out: PlanDict = {}
    notes: NoteDict = {}
    for dp in plan.sorted_days():
        day = dict(dp.slots)
        for slot, name in dp.sides.items():
            day[f"_보조_{slot}"] = name
        if dp.dessert:
            day["_디저트"] = dp.dessert
        out[dp.date] = day
        notes[dp.date] = dict(dp.reasons)
    return out, notes


def month_business_days(year: int, month: int, holidays=()) -> list:
    """주말·휴일을 뺀 영업일. holidays 는 ISO 문자열 리스트."""
    hol = {str(h) for h in holidays}
    d = datetime.date(year, month, 1)
    days = []
    while d.month == month:
        if d.weekday() < 5 and d.isoformat() not in hol:
            days.append(d)
        d += datetime.timedelta(days=1)
    return days
