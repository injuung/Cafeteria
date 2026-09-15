# -*- coding: utf-8 -*-
"""
표기명 선택 + 보조('&') 메뉴 부착.

레시피 ID 는 정체성(중복·로테이션 판정용),
별칭은 표시층(조리 어미가 겹칠 때 체감 다양성을 만드는 용도)이다.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Optional, Tuple

SCOPE_PREF = {
    "유아": ["공용", "유아우선", "미사용"],
    "성인": ["성인전용", "공용", "미사용", "유아우선"],
}

SUFFIX = re.compile(r"(찜|볶음|무침|조림|국|탕|구이|전|튀김)$")


def display_name(repo, rid: str, line: str = "유아") -> str:
    prefs = SCOPE_PREF.get(line, ["공용", "미사용"])
    aliases = repo.alias_by_rid.get(rid, [])
    for sc in prefs:
        cand = [a for a in aliases if a["scope"] == sc]
        if not cand:
            continue
        cand.sort(key=lambda a: (not a["is_rep"], -a["n_occ"]))
        return cand[0]["alias"]
    return repo[rid].rep


def choose_label(repo, rid: str, day: Dict[str, str], used_labels: Iterable[str],
                 scope_ok=("공용", "유아우선", "미사용")) -> Tuple[str, str]:
    """같은 날 조리 어미가 겹치면 별칭 풀에서 어미가 다른 표기를 고른다."""
    base = repo[rid].rep
    suf = SUFFIX.search(base)
    if not suf:
        return base, ""
    same = sum(1 for r2 in day.values()
               if isinstance(r2, str) and r2 in repo.recipes and r2 != rid
               and repo[r2].rep.endswith(suf.group(1)))
    if same == 0:
        return base, ""
    for a in repo.alias_by_rid.get(rid, []):
        if a["scope"] not in scope_ok:
            continue
        s2 = SUFFIX.search(a["alias"])
        if s2 and s2.group(1) != suf.group(1) and a["alias"] not in used_labels:
            return a["alias"], f"조리방식 중복 회피 → {base}에서 표기 변경"
    return base, ""


def attach_sides(repo, plan) -> None:
    """부모 메뉴 배치 후 보조('&')를 고른다. 최근 미사용 후보를 우선한다."""
    last_used: Dict[str, object] = {}
    for dp in plan.sorted_days():
        for slot, rid in list(dp.slots.items()):
            if not rid or slot.startswith("_"):
                continue
            cands = repo.sides.get(rid)
            if not cands:
                continue
            best: Optional[Tuple[str, str]] = None
            best_age = -1
            for nm, cnt, lastd in cands:
                srid = repo.rid_by_rep.get(nm)
                if not srid:
                    continue
                lu = last_used.get(srid)
                age = (dp.date - lu).days if lu else 9999
                if age > best_age:
                    best, best_age = (srid, nm), age
            if best:
                srid, nm = best
                dp.sides[slot] = nm
                last_used[srid] = dp.date
                dp.reasons[f"_보조_{slot}"] = (
                    f"{repo[rid].rep}의 보조 · 후보 {len(cands)}종 중 "
                    f"{'최근 미사용' if best_age >= 9999 else str(best_age) + '일 전 사용'}")
