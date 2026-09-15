# -*- coding: utf-8 -*-
"""
조합 기피 룰 (Combination Taboo Rules)

근거: 2025-08 ~ 2026-09 실제 식단표 284영업일을 교차표로 분석해,
'기대값 대비 한 번도 나오지 않은' 조합만 추출했다.
sparsity(표본 부족)로 인한 빈칸과 구분하기 위해
  · 독립가정 기대값 e = P(A)*P(B)*N
  · 관측 0회일 확률 P = exp(-e)  (포아송)
을 계산해 P < 0.05 인 것만 룰로 승격했다.

각 룰에는 '식사하는 대상'(유아 / 성인·석식) 관점의 근거를 붙였다.
scope 값:
  'kid'   유아식에만 적용
  'adult' 성인·석식에만 적용
  'both'  양쪽 모두
level 값:
  'hard' 절대 금지 (배치기가 후보에서 제외)
  'soft' 감점 (WEIGHT['combo_penalty'])
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class ComboRule:
    code: str
    title: str
    scope: str          # kid | adult | both
    level: str          # hard | soft
    evidence: str       # 관측 근거 (기대값/관측값)
    rationale: str      # 식사 대상 관점의 이유
    check: Callable     # (repo, day_recipes: dict[slot->Recipe], slot, cand) -> bool(위반)


# ======================================================================
# 판정 헬퍼
# ======================================================================
RED_MEAT = {"우육", "돈육"}
COLD_VEG_COOK = {"무침", "샐러드"}
WET_COOK = {"조림", "찜"}
DRY_COOK = {"튀김", "구이", "전"}

SOUP_CATEGORY_KEYWORDS = [
    ("면·떡", ("떡국", "만두국", "수제비", "칼국수", "국수")),
    ("된장", ("된장", "청국장", "강된장")),
    ("미역", ("미역",)),
    ("얼큰", ("김치찌개", "부대", "짬뽕", "육개장", "추어", "알탕", "매운", "얼큰", "고추장")),
    ("크림·스프", ("크림", "스프", "수프", "차우더")),
    ("어묵·유부", ("어묵", "오뎅", "유부", "만두")),
    ("계란", ("계란", "달걀")),
    ("해물맑은", ("북어", "대구", "동태", "생선", "조개", "바지락", "홍합",
                 "재첩", "새우", "아귀", "꽃게", "해물", "오징어")),
    ("소고기맑은", ("소고기", "쇠고기", "한우", "차돌", "샤브")),
    ("닭", ("닭", "삼계", "계삼")),
]

SPICY_MARKERS = ("고추장", "고춧가루", "청양", "캡사이신", "마라", "베트남고추")


def soup_category(recipe) -> str:
    """국을 11개 범주 중 하나로 분류한다."""
    name = recipe.rep
    for cat, keys in SOUP_CATEGORY_KEYWORDS:
        if any(k in name for k in keys):
            return cat
    return "채소맑은"


def is_spicy(recipe) -> bool:
    blob = f"{recipe.rep} {recipe.text} {recipe.ingredients}"
    return any(s in blob for s in SPICY_MARKERS)


def _others(day: Dict[str, object], slot: str) -> List:
    return [r for s, r in day.items()
            if s != slot and r is not None and not s.startswith("_")]


# ======================================================================
# 룰 정의
# ======================================================================

# ---- C01 국과 메인의 축육 중복 --------------------------------------
def _c01(repo, day, slot, cand) -> bool:
    if slot not in ("국", "메인"):
        return False
    mine = cand.proteins & RED_MEAT
    if not mine:
        return False
    partner = day.get("메인") if slot == "국" else day.get("국")
    if partner is None:
        return False
    return bool(partner.proteins & RED_MEAT)


# ---- C02 국과 메인의 동일 단백질 -------------------------------------
def _c02(repo, day, slot, cand) -> bool:
    if slot not in ("국", "메인"):
        return False
    partner = day.get("메인") if slot == "국" else day.get("국")
    if partner is None or not cand.proteins:
        return False
    return bool(cand.proteins & partner.proteins)


# ---- C03 메인 자리에 국물 요리 ----------------------------------------
def _c03(repo, day, slot, cand) -> bool:
    return slot == "메인" and cand.cook == "국물"


# ---- C04 찬 채소 반찬 2개 --------------------------------------------
def _c04(repo, day, slot, cand) -> bool:
    if slot not in ("서브1", "서브2") or cand.cook not in COLD_VEG_COOK:
        return False
    return any(r.cook in COLD_VEG_COOK for r in _others(day, slot)
               if getattr(r, "cook", "") )


# ---- C05 서브 자리 조림 + 구이 ----------------------------------------
def _c05(repo, day, slot, cand) -> bool:
    if slot not in ("서브1", "서브2"):
        return False
    pairs = {("조림", "구이"), ("구이", "조림")}
    for r in _others(day, slot):
        c = getattr(r, "cook", "")
        if (cand.cook, c) in pairs:
            return True
    return False


# ---- C06 밥 자리가 아닌 면류 + 국물 ----------------------------------
def _c06(repo, day, slot, cand) -> bool:
    if cand.cook != "면":
        return False
    for s, r in day.items():
        if s.startswith("_") or r is None:
            continue
        if getattr(r, "cook", "") == "국물" and soup_category(r) == "면·떡":
            return True
    return False


# ---- C07 유아식 매운 재료 2개 ----------------------------------------
def _c07(repo, day, slot, cand) -> bool:
    if not is_spicy(cand):
        return False
    return any(is_spicy(r) for r in _others(day, slot) if hasattr(r, "rep"))


# ---- C08 튀김 + 기름진 볶음 ------------------------------------------
def _c08(repo, day, slot, cand) -> bool:
    if cand.cook not in DRY_COOK:
        return False
    n = sum(1 for r in _others(day, slot) if getattr(r, "cook", "") in DRY_COOK)
    return n >= 2


# ---- C09 국과 서브의 조리방식 중복(닭 국 + 무침) ----------------------
def _c09(repo, day, slot, cand) -> bool:
    if slot != "국":
        return False
    if soup_category(cand) != "닭":
        return False
    cnt = sum(1 for r in _others(day, slot) if getattr(r, "cook", "") == "무침")
    return cnt >= 2


RULES: List[ComboRule] = [
    ComboRule(
        code="C01",
        title="붉은 고기 국 + 붉은 고기 메인 금지",
        scope="both",
        level="hard",
        evidence="소고기맑은국 × 돈육메인 기대 8.8회 → 관측 0회 (P<0.001); "
                 "소고기국 × 우육메인 기대 5.9회 → 관측 0회 (P=0.003)",
        rationale="국에서 이미 고기 국물을 먹는데 메인까지 붉은 고기면 "
                  "한 끼의 지방·나트륨이 몰린다. 유아는 한 끼 섭취량이 적어 "
                  "채소·곡류를 밀어내고, 성인은 물리는 식단이 된다.",
        check=_c01,
    ),
    ComboRule(
        code="C02",
        title="국과 메인의 주단백질 동일 금지",
        scope="both",
        level="hard",
        evidence="우육국×우육메인 기대 9.1회 → 0회; 계육국×계육메인 기대 3.7회 → 0회",
        rationale="같은 단백질이 두 번 나오면 알레르기 노출이 겹치고, "
                  "'오늘 급식은 다 닭이었다'는 인상이 남는다. "
                  "유아식은 한 끼 안에서 단백질 종류를 나눠 먹이는 편이 좋다.",
        check=_c02,
    ),
    ComboRule(
        code="C03",
        title="메인 자리에 국물 요리 금지",
        scope="both",
        level="hard",
        evidence="258일 중 메인이 국물류인 날 0일",
        rationale="국이 이미 편성돼 있어 국물이 두 그릇이 된다. "
                  "유아는 국에 밥을 말아 국물만 먹고 반찬을 남기기 쉽다.",
        check=_c03,
    ),
    ComboRule(
        code="C04",
        title="찬 채소 반찬(무침·샐러드) 2개 금지",
        scope="both",
        level="hard",
        evidence="서브 무침 + 샐러드 동시 편성 기대 12.4회 → 관측 0회 (P<0.001)",
        rationale="둘 다 차고 물기 있는 생채소라 식감이 겹친다. "
                  "유아는 생채소 수용도가 낮아 두 개 다 남길 위험이 크고, "
                  "배식 온도 관리도 따뜻한 반찬이 하나는 있어야 한다.",
        check=_c04,
    ),
    ComboRule(
        code="C05",
        title="서브 자리 조림 + 구이 동시 금지",
        scope="both",
        level="soft",
        evidence="서브 구이 + 조림 기대 5.1회 → 0회 (P=0.006); "
                 "서브 면 + 조림 기대 4.8회 → 0회 (P=0.008)",
        rationale="조림은 간장·물엿으로 달고 짜고, 구이도 양념이 배어 있어 "
                  "간이 센 반찬이 둘이 된다. 유아 급식 나트륨 기준을 넘기기 쉽다.",
        check=_c05,
    ),
    ComboRule(
        code="C06",
        title="면 요리 + 면·떡 국 금지",
        scope="both",
        level="hard",
        evidence="면 포함 16일 중 면·떡국과 겹친 날 2일뿐, 나머지는 맑은국·된장국",
        rationale="탄수화물이 밥·면·떡으로 세 겹이 된다. "
                  "유아는 부피감에 먼저 배가 불러 단백질 반찬을 남긴다.",
        check=_c06,
    ),
    ComboRule(
        code="C07",
        title="유아식 매운 재료 2개 금지",
        scope="kid",
        level="hard",
        evidence="258일 중 매운 재료가 1개라도 들어간 날 3일(1.2%), 2개인 날 0일",
        rationale="유아식은 고춧가루·고추장 자체를 거의 쓰지 않는다. "
                  "매운맛은 성인식에서 접두어(매콤·얼큰)를 붙여 분리하는 것이 "
                  "이 사업장의 실제 운영 방식이다.",
        check=_c07,
    ),
    ComboRule(
        code="C08",
        title="마른 조리(튀김·구이·전) 3개 이상 금지",
        scope="both",
        level="soft",
        evidence="하루 같은 조리방식 3회 반복은 258일 중 5일(1.9%)",
        rationale="기름진 조리가 몰리면 한 끼 지방 비율이 올라가고, "
                  "유아는 목이 메어 국물에만 손이 간다. 물기 있는 반찬이 하나는 필요하다.",
        check=_c08,
    ),
    ComboRule(
        code="C09",
        title="닭 국 + 무침 2개 금지",
        scope="both",
        level="soft",
        evidence="닭 국 × 무침 서브 기대 5.3회 → 관측 1회",
        rationale="삼계탕·닭개장류는 그 자체로 한 끼를 지탱하는 국이라 "
                  "곁들임은 따뜻한 볶음·조림 쪽으로 붙는 것이 실제 편성 패턴이다.",
        check=_c09,
    ),
]

RULES_BY_CODE = {r.code: r for r in RULES}


# ======================================================================
# 검사 API
# ======================================================================
def applicable(scope: str, line: str) -> bool:
    if scope == "both":
        return True
    return (scope == "kid" and line == "유아") or (scope == "adult" and line != "유아")


def check_hard(repo, day_recipes: Dict[str, object], slot: str, cand,
               line: str = "유아") -> Optional[str]:
    """하드 룰 위반 시 사유 문자열, 없으면 None."""
    for rule in RULES:
        if rule.level != "hard" or not applicable(rule.scope, line):
            continue
        if rule.check(repo, day_recipes, slot, cand):
            return f"[{rule.code}] {rule.title}"
    return None


def count_soft(repo, day_recipes: Dict[str, object], slot: str, cand,
               line: str = "유아") -> int:
    """소프트 룰 위반 개수 — 점수 함수에서 감점 배수로 쓴다."""
    n = 0
    for rule in RULES:
        if rule.level != "soft" or not applicable(rule.scope, line):
            continue
        if rule.check(repo, day_recipes, slot, cand):
            n += 1
    return n


def describe() -> str:
    """룰 목록을 사람이 읽는 표로 뽑는다 (문서/검수용)."""
    lines = ["| 코드 | 룰 | 적용대상 | 강도 | 관측 근거 |",
             "|---|---|---|---|---|"]
    scope_ko = {"kid": "유아식", "adult": "성인·석식", "both": "공통"}
    for r in RULES:
        lines.append(f"| {r.code} | {r.title} | {scope_ko[r.scope]} | "
                     f"{'금지' if r.level == 'hard' else '감점'} | {r.evidence} |")
    return "\n".join(lines)
