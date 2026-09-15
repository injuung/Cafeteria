# -*- coding: utf-8 -*-
"""
성인·석식 변형.

데이터 사실: 유아↔성인 상이 건 중 약 95%가 '다른 레시피로 교체'이고
별칭(매운맛 표기) 교체는 5%뿐이다. 따라서 과거 이력에서 교체쌍을 학습한다.

담당자 확정(2026-09) — 변형으로 인정할 관계:
  ① 같은 레시피 · 표기만 다름            → 인정
  ② 매콤/얼큰 접두 (고춧가루 추가)         → 인정
  ③ 양념·재료 추가 (진미채 → 양념진미채)    → 인정
  ④ 메뉴 자체 교체                      → 인정하지 않음
     (납품처 '식상하다' 피드백에 따른 비정기 변경이라 예측 불가.
      유아식과 동일하게 두고 담당자가 후처리한다.)
"""
from __future__ import annotations

import collections
import copy
import re
from typing import Dict, Tuple

from src.config.constants import (
    ADULT_LEARN_MONTHS,
    ADULT_SWAP_SLOTS,
    KIMCHI_SWAP_MONTHLY,
    MILD_KIMCHI,
    SLOTS,
    SPICY_KIMCHI,
)
from src.domain.models import DayPlan, MonthPlan
from src.rules.hard import violates
from src.rules.state import NullState

MOD_PREFIX = re.compile(r"^(매콤한|매콤|얼큰|매운|빨간|마라|고추장|양념|칼칼)")


def is_variation(repo, rid_kid: str, rid_adult: str) -> bool:
    if rid_kid == rid_adult:
        return True                                                    # ①
    a = repo[rid_kid].rep
    b = repo[rid_adult].rep
    if MOD_PREFIX.match(b) and MOD_PREFIX.sub("", b) == a:
        return True                                                    # ②
    if a in b:
        return True                                                    # ③ '추가' 방향만
    return False                                                       # ④


def build_swap_map(repo, cut_date: str, months: int = ADULT_LEARN_MONTHS):
    """최근 N개월 유아↔성인 비교 → {(자리, 유아rid): Counter(성인rid)}."""
    y, m = int(cut_date[:4]), int(cut_date[5:7])
    m -= months
    while m <= 0:
        m += 12
        y -= 1
    start = f"{y:04d}-{m:02d}-01"

    by: Dict[Tuple[str, str], Dict[str, str]] = collections.defaultdict(dict)
    for d, ln, sl, rid, nm in repo.history:
        if ln in ("유아", "성인") and sl and start <= d < cut_date:
            by[(d, ln)][sl] = rid

    swap = collections.defaultdict(collections.Counter)
    seen: collections.Counter = collections.Counter()
    dropped = 0
    for d in sorted({x for x, _ in by}):
        kid, adult = by.get((d, "유아")), by.get((d, "성인"))
        if not kid or not adult:
            continue
        for sl in ADULT_SWAP_SLOTS:
            if sl in kid and sl in adult:
                seen[(sl, kid[sl])] += 1
                if kid[sl] != adult[sl]:
                    if is_variation(repo, kid[sl], adult[sl]):
                        swap[(sl, kid[sl])][adult[sl]] += 1
                    else:
                        dropped += 1
    return swap, seen, dropped


def to_adult(repo, plan: MonthPlan, swap=None, seen=None) -> MonthPlan:
    """유아식 확정본 → 성인·초등 변형본.
       밥은 손대지 않고, 김치는 월 KIMCHI_SWAP_MONTHLY 회만 바꾼다."""
    swap = swap or {}
    seen = seen or collections.Counter()
    null = NullState()

    out = MonthPlan(year=plan.year, month=plan.month, line="성인")
    kimchi_used = 0

    for dp in plan.sorted_days():
        slots = dict(dp.slots)
        why: Dict[str, str] = {}

        for sl in SLOTS:
            rid = dp.slots.get(sl)
            if not rid:
                continue
            if sl == "밥":
                why[sl] = "유아식과 동일 (담당자 확정: 밥은 동일 진행)"
                continue

            picked = None
            if sl in ADULT_SWAP_SLOTS:
                cands = swap.get((sl, rid))
                if cands:
                    total = max(1, seen.get((sl, rid), 1))
                    if sum(cands.values()) / total >= 0.5:
                        for cand_rid, c in cands.most_common():
                            if cand_rid in slots.values() or cand_rid not in repo.recipes:
                                continue
                            if not repo[cand_rid].is_active:
                                continue     # 담당자가 끈 메뉴는 변형에도 쓰지 않는다
                            probe = {k: v for k, v in slots.items()
                                     if k != sl and not k.startswith("_")
                                     and v in repo.recipes}
                            if not violates(repo, null, dp.date, probe, sl,
                                            cand_rid, line="성인"):
                                picked = (cand_rid, f"성인식 맛 조정 · 과거 {c}회 관측")
                                break

            # 김치 — 유아 백김치인 날 중 월 2회만 매운 김치로
            if (picked is None and sl == "김치"
                    and repo[rid].rep == MILD_KIMCHI
                    and kimchi_used < KIMCHI_SWAP_MONTHLY):
                for nm in SPICY_KIMCHI:
                    crid = repo.rid_by_rep.get(nm)
                    if not crid or not repo[crid].is_active:
                        continue
                    probe = {k: v for k, v in slots.items()
                             if k != sl and not k.startswith("_") and v in repo.recipes}
                    if not violates(repo, null, dp.date, probe, sl, crid, line="성인"):
                        picked = (crid, f"백김치 → 매운 김치 "
                                        f"(월 {KIMCHI_SWAP_MONTHLY}회 중 {kimchi_used + 1}번째)")
                        kimchi_used += 1
                        break

            if picked:
                slots[sl] = picked[0]
                why[sl] = picked[1]
            else:
                why[sl] = "유아식과 동일"

        out.days[dp.date] = DayPlan(
            date=dp.date, slots=slots, sides=copy.deepcopy(dp.sides),
            reasons=why, dessert=dp.dessert, is_feast=dp.is_feast)
    return out


def divergence(kid: MonthPlan, adult: MonthPlan) -> float:
    """유아식 대비 성인식이 달라진 칸의 비율(%)."""
    tot = diff = 0
    for d, dp in kid.days.items():
        ap = adult.days.get(d)
        if not ap:
            continue
        for sl, rid in dp.slots.items():
            tot += 1
            if ap.slots.get(sl) != rid:
                diff += 1
    return round(diff / tot * 100, 1) if tot else 0.0
