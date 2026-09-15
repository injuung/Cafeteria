# -*- coding: utf-8 -*-
"""
키즈락 식단표 자동 초안 생성기 — CLI 진입점.

사용법
    python -m src.main pipeline            # 1~3단계: 원천 엑셀 → master.json
    python -m src.main master              # 레시피북 마스터 xlsx 출력
    python -m src.main plan 2026-11        # 해당 월 생산일지 초안 생성
    python -m src.main plan 2026-11 --holidays 2026-11-05,2026-11-06
    python -m src.main analyze             # 조합 분석 리포트(나오지 않은 패턴)
    python -m src.main rules               # 조합 기피 룰 목록 출력
    python -m src.main verify 2026-07      # 과거 달 재현 테스트
"""
from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import paths  # noqa: E402


# ----------------------------------------------------------------------
def cmd_pipeline(args) -> int:
    for mod in ("src.extract.step1_parse",
                "src.extract.step2_group",
                "src.extract.step3_tag"):
        print(f"\n─── {mod} ───")
        runpy.run_module(mod, run_name="__main__")
    return 0


def cmd_master(args) -> int:
    runpy.run_module("src.export.recipe_book", run_name="__main__")
    return 0


def cmd_plan(args) -> int:
    from src.export.adapters import month_business_days
    from src.export.production_sheet import build

    ym = args.ym
    year, month = int(ym[:4]), int(ym[5:7])
    holidays = [h.strip() for h in (args.holidays or "").split(",") if h.strip()]
    days = month_business_days(year, month, holidays)

    paths.ensure_dirs()
    out = args.out or (paths.OUTPUT_DIR / f"{month}월_생산일지_초안.xlsx")
    print(f"{ym} 초안 생성 — 영업일 {len(days)}일, 휴일 {holidays or '없음'}")
    kid, adult, fails = build(ym, str(out), days=days)
    if fails:
        print(f"  배치 실패 {len(fails)}건:")
        for d, why in fails:
            print(f"    {d} — {why}")
    else:
        print("  배치 실패 0건")
    print(f"  저장: {out}")
    return 0


def cmd_analyze(args) -> int:
    from src.analysis import build_days
    from src.analysis.combination_stats import day_features, report
    from src.domain.repository import Repository

    if not paths.DAYS_JSON.exists() or args.rebuild:
        build_days.main([args.line])
    repo = Repository()
    rows = day_features(repo, paths.DAYS_JSON)
    text = report(rows)
    print(text)
    out = paths.OUTPUT_DIR / "조합분석_리포트.md"
    paths.ensure_dirs()
    out.write_text(text, encoding="utf-8")
    print(f"\n저장: {out}")
    return 0


def cmd_rules(args) -> int:
    from src.rules.combination import RULES, describe

    print(describe())
    print("\n\n## 룰별 근거")
    for r in RULES:
        print(f"\n### [{r.code}] {r.title}")
        print(f"- 적용대상: {r.scope} / 강도: {r.level}")
        print(f"- 관측: {r.evidence}")
        print(f"- 이유: {r.rationale}")
    return 0


def cmd_verify(args) -> int:
    from src.verify.reproduce import run

    run(args.ym)
    return 0


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kizrock", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("pipeline", help="원천 엑셀 → master.json").set_defaults(fn=cmd_pipeline)
    sub.add_parser("master", help="레시피북 마스터 xlsx").set_defaults(fn=cmd_master)

    sp = sub.add_parser("plan", help="월별 생산일지 초안")
    sp.add_argument("ym", help="YYYY-MM")
    sp.add_argument("--holidays", help="쉼표 구분 ISO 날짜")
    sp.add_argument("--out", help="출력 경로")
    sp.set_defaults(fn=cmd_plan)

    sa = sub.add_parser("analyze", help="조합 분석 리포트")
    sa.add_argument("--line", default="유아")
    sa.add_argument("--rebuild", action="store_true")
    sa.set_defaults(fn=cmd_analyze)

    sub.add_parser("rules", help="조합 기피 룰 목록").set_defaults(fn=cmd_rules)

    sv = sub.add_parser("verify", help="과거 달 재현 테스트")
    sv.add_argument("ym", help="YYYY-MM")
    sv.set_defaults(fn=cmd_verify)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
