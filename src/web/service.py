# -*- coding: utf-8 -*-
"""웹 화면용: 달력 미리보기 + 초안 생성 + JSON 직렬화."""
from __future__ import annotations

import calendar
import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from src.config import paths
from src.config.constants import READY_MAIN_MAX, SLOTS
from src.domain.repository import Repository
from src.export.adapters import month_business_days
from src.export.production_sheet import LEGEND, MENU_ROWS, build
from src.planner.adult import divergence
from src.planner.calendar import feast_days, gim_days
from src.planner.labels import display_name
from src.rules.combination import RULES
from src.web.holidays import holiday_name, month_holidays

WD = ["월", "화", "수", "목", "금", "토", "일"]


def get_repo() -> Repository:
    return _load_repo(
        paths.MASTER_JSON.stat().st_mtime,
        paths.RAW_JSON.stat().st_mtime,
        paths.GROUPS_JSON.stat().st_mtime,
    )


@lru_cache(maxsize=1)
def _load_repo(_m, _r, _g) -> Repository:
    return Repository()


def meta() -> dict:
    repo = get_repo()
    months = repo.months()
    today = datetime.date.today()
    nxt = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    return {
        "today": today.isoformat(),
        "default_ym": f"{nxt.year:04d}-{nxt.month:02d}",
        "history_months": months,
        "recipe_count": sum(1 for r in repo.recipes.values() if r.is_active),
        "data_from": months[0] if months else None,
        "data_to": months[-1] if months else None,
    }


def calendar_view(ym: str, holidays: Optional[Iterable[str]] = None) -> dict:
    year, month = _parse_ym(ym)
    public = month_holidays(ym)
    hol = list(holidays) if holidays is not None else [h["date"] for h in public]
    hol_set = set(hol)
    biz = month_business_days(year, month, hol)
    feast = [d.isoformat() for d in feast_days(biz)]
    gim = [d.isoformat() for d in gim_days(biz, feast_days(biz))]

    first_wd, n_days = calendar.monthrange(year, month)
    cells = []
    # 앞쪽 빈칸 — 월요일 시작
    for _ in range(first_wd):
        cells.append(None)
    for day in range(1, n_days + 1):
        d = datetime.date(year, month, day)
        iso = d.isoformat()
        cells.append({
            "date": iso,
            "day": day,
            "weekday": d.weekday(),
            "weekday_label": WD[d.weekday()],
            "weekend": d.weekday() >= 5,
            "holiday": iso in hol_set,
            "holiday_name": holiday_name(iso) if iso in hol_set else None,
            "business": d in biz,
            "feast": iso in feast,
            "gim": iso in gim,
        })
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]
    return {
        "ym": ym,
        "year": year,
        "month": month,
        "public_holidays": public,
        "holidays": sorted(hol_set),
        "business_days": len(biz),
        "feast": feast,
        "gim": gim,
        "weeks": weeks,
    }


def generate_plan(ym: str, holidays: Iterable[str]) -> dict:
    year, month = _parse_ym(ym)
    hol = [h.strip() for h in holidays if h and h.strip()]
    days = month_business_days(year, month, hol)
    paths.ensure_dirs()
    stored = f"plan_{ym}.xlsx"
    filename = f"{month}월_생산일지_초안.xlsx"
    out = paths.OUTPUT_DIR / stored
    kid, adult, fails = build(ym, str(out), days=days)
    repo = get_repo()
    feast = feast_days(days)
    gim = gim_days(days, feast)
    ready = sum(
        1 for dp in kid.sorted_days()
        if (rid := dp.slots.get("메인")) and repo.get(rid) and repo[rid].ready
    )
    return {
        "ym": ym,
        "holidays": hol,
        "stats": {
            "business_days": len(days),
            "failures": len(fails),
            "divergence": divergence(kid, adult),
            "ready_main": ready,
            "ready_main_max": READY_MAIN_MAX,
            "feast": [d.isoformat() for d in feast],
            "gim": [d.isoformat() for d in gim],
        },
        "failures": [
            {"date": d.isoformat() if hasattr(d, "isoformat") else str(d), "reason": why}
            for d, why in fails
        ],
        "kid": [_serialize_day(repo, dp, "유아") for dp in kid.sorted_days()],
        "adult": [_serialize_day(repo, dp, "성인") for dp in adult.sorted_days()],
        "menu_rows": MENU_ROWS,
        "legend": LEGEND,
        "title_kid": f"{month:02d}월 식단표",
        "title_adult": f"{month:02d}월 식단표",
        "sheet_kid": "유아식단표",
        "sheet_adult": "글로벌리더스&석식식단표",
        "download": f"/api/files/{stored}",
        "filename": filename,
    }


def rules() -> list[dict]:
    scope_ko = {"kid": "유아식", "adult": "성인·석식", "both": "공통"}
    return [
        {
            "code": r.code,
            "title": r.title,
            "scope": r.scope,
            "scope_label": scope_ko[r.scope],
            "level": r.level,
            "level_label": "금지" if r.level == "hard" else "감점",
            "evidence": r.evidence,
            "rationale": r.rationale,
        }
        for r in RULES
    ]


def verify(ym: str) -> dict:
    from src.verify.reproduce import run

    raw = run(ym, verbose=False)
    if raw is None:
        return {"ym": ym, "empty": True, "message": f"{ym}에는 실제 편성 데이터가 없습니다."}
    met = raw["metrics"]
    return {
        "ym": ym,
        "empty": False,
        "business_days": len(raw["actual"]),
        "failures": len(raw["fails"]),
        "exact_rate": round(met["exact_rate"] * 100, 1),
        "exact": f'{met["exact"]}/{met["slots"]}',
        "set_rate": round(met["set_rate"] * 100, 1),
        "set": f'{met["set_hit"]}/{met["set_tot"]}',
        "protein_rate": round(met["protein_rate"] * 100, 1),
        "cook_rate": round(met["cook_rate"] * 100, 1),
        "gen_violations": len(raw["gen_viol"]),
        "act_violations": len(raw["act_viol"]),
        "set_by_slot": {
            k: f"{v[0]}/{v[1]}" for k, v in met["set_by_slot"].items()
        },
        "note": "칸 단위 일치가 낮은 것은 정상입니다. 같은 규칙 안에서도 날짜별 배치는 자유도가 큽니다. "
                "메뉴 집합 일치와 하드 제약 위반을 먼저 보세요.",
    }


def output_file(name: str) -> Path:
    safe = Path(name).name
    path = (paths.OUTPUT_DIR / safe).resolve()
    if path.parent != paths.OUTPUT_DIR.resolve() or not path.is_file():
        raise FileNotFoundError(safe)
    return path


def _fmt_allergy(raw: str | None) -> str:
    if not raw or raw.strip() in {"0", "-", "."}:
        return "0"
    codes = raw.strip().strip(".")
    return f".{codes}." if codes else "0"


def _allergy_of(repo, name: str) -> str:
    rec = repo.by_name(name)
    return _fmt_allergy(rec.allergy if rec else "")


def _serialize_day(repo, dp, line: str) -> dict:
    rows = []
    for slot in SLOTS:
        rid = dp.slots.get(slot)
        if not rid:
            continue
        rec = repo.get(rid)
        name = display_name(repo, rid, line)
        rows.append({
            "name": name,
            "allergy": _fmt_allergy(rec.allergy if rec else ""),
            "is_side": False,
            "slot": slot,
            "reason": dp.reasons.get(slot, ""),
        })
        side = dp.sides.get(slot)
        if side:
            label = side if str(side).startswith("&") else f"& {side}"
            rows.append({
                "name": label,
                "allergy": _allergy_of(repo, side),
                "is_side": True,
                "slot": slot,
                "reason": dp.reasons.get(f"_보조_{slot}", ""),
            })
    if dp.dessert:
        rows.append({
            "name": dp.dessert,
            "allergy": _allergy_of(repo, dp.dessert),
            "is_side": False,
            "slot": "디저트",
            "reason": "생일파티 특식 디저트",
        })
    return {
        "date": dp.date.isoformat(),
        "day": dp.date.day,
        "month": dp.date.month,
        "weekday": dp.date.weekday(),
        "weekday_label": WD[dp.date.weekday()],
        "is_feast": dp.is_feast,
        "rows": rows,
    }


def _parse_ym(ym: str) -> tuple[int, int]:
    try:
        year, month = int(ym[:4]), int(ym[5:7])
        datetime.date(year, month, 1)
    except Exception as exc:
        raise ValueError("월은 YYYY-MM 형식이어야 합니다.") from exc
    if len(ym) != 7 or ym[4] != "-":
        raise ValueError("월은 YYYY-MM 형식이어야 합니다.")
    return year, month
