# -*- coding: utf-8 -*-
"""도메인 모델 — 레시피 / 하루 편성 / 배치 사유."""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Recipe:
    """레시피 1건. '레시피 ID'가 정체성이고, '별칭'은 표시용이다."""

    recipe_id: str
    rep: str                    # 대표 표기명
    status: str = "활성"
    in_book: bool = True
    aliases: List[str] = field(default_factory=list)
    slot_dist: str = ""         # '메인12, 서브1 3' 처럼 자리별 사용횟수
    line_dist: str = ""         # '유아4, 성인4'
    protein: str = ""           # '우육, 돈육'
    cook: str = ""              # 구이/볶음/조림/무침/튀김/국물/전/면/샐러드/밥/김치/기타
    ready: bool = False         # 완제품(완조리) 여부
    ready_score: int = 0
    allergy: str = ""           # '2.5.6.12'
    ingredients: str = ""       # 정규화된 재료 목록
    text: str = ""              # 자재사용내역 원문
    memo: str = ""
    weight_g: Optional[int] = None
    n_occ: int = 0
    first: str = ""
    last: str = ""
    active_flag: str = "O"      # 담당자가 시트에서 X 로 끄면 배치 제외
    is_side: bool = False       # '&' 로 시작하는 보조 메뉴
    side_candidates: List = field(default_factory=list)

    # ---- 파생 ----
    @property
    def proteins(self) -> Set[str]:
        return {x.strip() for x in self.protein.split(",") if x.strip()}

    @property
    def allergy_codes(self) -> Set[int]:
        return {int(x) for x in self.allergy.split(".") if x.strip().isdigit()}

    @property
    def is_active(self) -> bool:
        return self.status.startswith("활성") and self.active_flag == "O"

    @classmethod
    def from_dict(cls, d: dict) -> "Recipe":
        known = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class DayPlan:
    """하루치 편성. slots 는 자리→recipe_id, sides 는 자리→보조 메뉴명."""

    date: datetime.date
    slots: Dict[str, str] = field(default_factory=dict)
    sides: Dict[str, str] = field(default_factory=dict)
    reasons: Dict[str, str] = field(default_factory=dict)
    dessert: Optional[str] = None
    is_feast: bool = False

    def recipe_ids(self) -> List[str]:
        return [r for r in self.slots.values() if r]

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "slots": dict(self.slots),
            "sides": dict(self.sides),
            "reasons": dict(self.reasons),
            "dessert": self.dessert,
            "is_feast": self.is_feast,
        }


@dataclass
class MonthPlan:
    """한 달치 편성 결과."""

    year: int
    month: int
    line: str                   # '유아' | '성인'
    days: Dict[datetime.date, DayPlan] = field(default_factory=dict)
    failures: List = field(default_factory=list)

    @property
    def ym(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def sorted_days(self) -> List[DayPlan]:
        return [self.days[d] for d in sorted(self.days)]
