# -*- coding: utf-8 -*-
"""
데이터 저장소 — master.json / raw.json / groups.json 을 읽어
레시피·별칭·편성이력을 한 곳에서 제공한다.
"""
from __future__ import annotations

import collections
import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import paths
from src.domain.models import Recipe

HistRow = Tuple[str, str, str, str, str]   # (date, line, slot, recipe_id, 표기명)


class Repository:
    def __init__(
        self,
        master_json: Optional[Path] = None,
        raw_json: Optional[Path] = None,
        groups_json: Optional[Path] = None,
    ):
        master_json = Path(master_json or paths.MASTER_JSON)
        raw_json = Path(raw_json or paths.RAW_JSON)
        groups_json = Path(groups_json or paths.GROUPS_JSON)

        M = json.loads(master_json.read_text(encoding="utf-8"))
        D = json.loads(raw_json.read_text(encoding="utf-8"))

        self.recipes: Dict[str, Recipe] = {
            m["recipe_id"]: Recipe.from_dict(m) for m in M["master"]
        }
        self.raw_master: Dict[str, dict] = {m["recipe_id"]: m for m in M["master"]}
        self.alias_rows: List[dict] = M["alias"]
        self.records: List[dict] = D["records"]
        self.kid_adult: List[dict] = D.get("kid_adult", [])
        self.rid_of: Dict[str, str] = json.loads(
            groups_json.read_text(encoding="utf-8")
        )["rid"]

        self.alias_by_rid: Dict[str, List[dict]] = collections.defaultdict(list)
        for a in self.alias_rows:
            self.alias_by_rid[a["recipe_id"]].append(a)

        self.rid_by_rep: Dict[str, str] = {r.rep: rid for rid, r in self.recipes.items()}
        self.sides: Dict[str, list] = {
            rid: m["side_candidates"]
            for rid, m in self.raw_master.items()
            if m.get("side_candidates")
        }

        self.history: List[HistRow] = sorted(
            (r["date"], r["line"] or "", r["slot"] or "", self.rid_of[r["name"]], r["name"])
            for r in self.records
            if r["name"] in self.rid_of
        )

    # ------------------------------------------------------------------
    @property
    def master(self) -> Dict[str, dict]:
        """엑셀 출력기가 쓰는 원본 dict 뷰 (Recipe 데이터클래스 이전 형태)."""
        return self.raw_master

    # ------------------------------------------------------------------
    def __getitem__(self, rid: str) -> Recipe:
        return self.recipes[rid]

    def get(self, rid: str) -> Optional[Recipe]:
        return self.recipes.get(rid)

    def by_name(self, name: str) -> Optional[Recipe]:
        rid = self.rid_by_rep.get(name) or self.rid_of.get(name)
        return self.recipes.get(rid) if rid else None

    # ------------------------------------------------------------------
    def history_before(self, cut_date: str, line: str = "유아") -> List[HistRow]:
        """재현 테스트 시 정보 누설을 막기 위해 기준일 이전 이력만 돌려준다."""
        return [h for h in self.history if h[0] < cut_date and h[1] == line]

    def business_days(self, ym: str, line: str = "유아") -> List[datetime.date]:
        ds = sorted({h[0] for h in self.history if h[0][:7] == ym and h[1] == line and h[2]})
        return [datetime.date.fromisoformat(d) for d in ds]

    def months(self) -> List[str]:
        return sorted({h[0][:7] for h in self.history})
