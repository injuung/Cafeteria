# -*- coding: utf-8 -*-
"""캘린더 골격 — 생일파티 특식일 / 도시락김 금요일."""
from __future__ import annotations

import datetime
from typing import List

from src.config.constants import FEAST_NTH_FRIDAY, GIM_MONTHLY


def nth_weekday(d: datetime.date) -> int:
    """그 달에서 몇 번째 해당 요일인가."""
    return sum(1 for x in range(1, d.day + 1)
               if datetime.date(d.year, d.month, x).weekday() == d.weekday())


def feast_days(days: List[datetime.date]) -> List[datetime.date]:
    """생일파티 특식일.

    담당자 확정: 보통 3주차 금요일. 단 그 달 1일이 금요일이면 한 주 밀리고,
    대상 금요일이 휴무면 그 이후 첫 금요일로 옮긴다.
    """
    fri = sorted(d for d in days if d.weekday() == 4)
    if not fri:
        return []
    first = fri[0].replace(day=1)
    shift = 1 if first.weekday() == 4 else 0
    target = FEAST_NTH_FRIDAY + shift
    for d in fri:
        if nth_weekday(d) == target:
            return [d]
    later = [d for d in fri if nth_weekday(d) > target]
    return later[:1] if later else fri[-1:]


def gim_days(days: List[datetime.date],
             feast: List[datetime.date]) -> List[datetime.date]:
    """도시락김 편성 금요일 — 특식일 제외, 월 앞·뒤로 분산."""
    fri = [d for d in days if d.weekday() == 4 and d not in feast]
    if len(fri) <= GIM_MONTHLY:
        return fri
    idx = [0, len(fri) - 1] if GIM_MONTHLY == 2 else list(range(GIM_MONTHLY))
    return [fri[i] for i in idx]
