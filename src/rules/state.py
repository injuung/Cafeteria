# -*- coding: utf-8 -*-
"""배치 진행 중의 컨텍스트 — 마지막 편성일 / 월 사용횟수 / 월간 상한 카운터."""
from __future__ import annotations

import collections
import datetime
from typing import Dict, List

from src.rules.pools import is_donburi


class PlacementState:
    def __init__(self, repo, cut_date: str, line: str = "유아"):
        self.repo = repo
        self.line = line
        self.last_seen: Dict[str, datetime.date] = {}
        for d, ln, sl, rid, nm in repo.history_before(cut_date, line):
            self.last_seen[rid] = datetime.date.fromisoformat(d)
        self.freq = collections.Counter(h[3] for h in repo.history_before(cut_date, line))
        self.month_use: collections.Counter = collections.Counter()
        self.ready_main = 0
        self.donburi = 0
        self.days: Dict[datetime.date, Dict[str, str]] = {}

    # ------------------------------------------------------------------
    def gap(self, rid: str, d: datetime.date) -> int:
        ls = self.last_seen.get(rid)
        return (d - ls).days if ls else 9999

    def week_key(self, d: datetime.date):
        return d.isocalendar()[:2]

    def week_days(self, d: datetime.date) -> List[datetime.date]:
        wk = self.week_key(d)
        return [x for x in self.days if self.week_key(x) == wk]

    def commit(self, d: datetime.date, slots: Dict[str, str]) -> None:
        self.days[d] = dict(slots)
        for slot, rid in slots.items():
            if not rid or slot.startswith("_"):
                continue
            self.month_use[rid] += 1
            self.last_seen[rid] = d
        main = slots.get("메인")
        if main and main in self.repo.recipes:
            if self.repo[main].ready:
                self.ready_main += 1
            if is_donburi(self.repo[main]):
                self.donburi += 1


class NullState:
    """당일 제약만 보고 월간 상한·로테이션은 무시하는 더미 상태 (성인식 변형용)."""

    month_use = collections.Counter()
    ready_main = 0
    donburi = 0
    days: dict = {}

    def gap(self, rid, d):
        return 9999

    def week_key(self, d):
        return d.isocalendar()[:2]

    def week_days(self, d):
        return []
