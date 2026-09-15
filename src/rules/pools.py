# -*- coding: utf-8 -*-
"""자리별 후보 풀 구성."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Tuple

from src.config.constants import FEAST_ONLY, KIMCHI_TYPES, SLOTS

SLOT_PART = re.compile(r"^(밥|메인|서브1|서브2|김치|국)(\d+)$")

# 덮밥소스류 — '덮밥소스'로 끝나지 않는 실물도 잡는다
DONBURI_MARKERS = ("덮밥소스", "하이라이스", "커리소스", "카레소스", "짜장소스")


def _f(recipe, field: str) -> str:
    """Recipe 데이터클래스와 master.json 원본 dict 를 모두 받는다."""
    if isinstance(recipe, dict):
        return recipe.get(field, "") or ""
    return getattr(recipe, field, "") or ""


def is_salad(recipe) -> bool:
    return _f(recipe, "cook") == "샐러드" or "샐러드" in _f(recipe, "rep")


def is_donburi(recipe) -> bool:
    """덮밥소스류. '덮밥소스'로 끝나지 않는 코코넛커리소스·비프하이라이스소스도 잡는다."""
    return any(k in _f(recipe, "rep") for k in DONBURI_MARKERS)


def line_allows(repo, rid: str, line: str) -> bool:
    """유아식에는 표기가 전부 '성인전용'인 레시피를 넣지 않는다."""
    if line != "유아":
        return True
    scopes = {a["scope"] for a in repo.alias_by_rid.get(rid, [])}
    if not scopes:
        return True
    return bool(scopes & {"공용", "유아우선", "미사용"})


def build_pools(repo, blacklist: Iterable[str] = (), line: str = "유아"
                ) -> Dict[str, List[Tuple[str, int]]]:
    """자리 → [(recipe_id, 과거 사용횟수)] 내림차순."""
    black = set(blacklist)
    pools: Dict[str, List[Tuple[str, int]]] = {s: [] for s in SLOTS}
    for rid, r in repo.recipes.items():
        if not r.is_active:
            continue
        if r.is_side:
            continue
        if not line_allows(repo, rid, line):
            continue
        if r.rep in black or rid in black:
            continue
        if r.rep in FEAST_ONLY:
            continue
        for part in (r.slot_dist or "").split(", "):
            m = SLOT_PART.match(part.strip())
            if not m:
                continue
            slot, cnt = m.group(1), int(m.group(2))
            if slot == "김치" and r.rep not in KIMCHI_TYPES:
                continue
            pools[slot].append((rid, cnt))
    for s in pools:
        pools[s].sort(key=lambda t: -t[1])
    return pools
