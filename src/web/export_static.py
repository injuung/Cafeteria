# -*- coding: utf-8 -*-
"""GitHub Pages 용 정적 사이트를 만든다.

    python -m src.web.export_static --out site
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from src.config import paths
from src.web import service
from src.web.holidays import HOLIDAYS, month_holidays

STATIC = Path(__file__).resolve().parent / "static"
DEMO_YM = "2026-11"
VERIFY_YMS = ("2026-07", "2026-08")


def export(out: Path, ym: str = DEMO_YM) -> Path:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    (out / "data").mkdir()
    (out / ".nojekyll").write_text("", encoding="utf-8")

    shutil.copy(STATIC / "index.html", out / "index.html")
    shutil.copy(STATIC / "styles.css", out / "static" / "styles.css")
    shutil.copy(STATIC / "app.js", out / "static" / "app.js")

    meta = service.meta()
    meta["default_ym"] = ym
    meta["static"] = True
    (out / "data" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "data" / "rules.json").write_text(
        json.dumps({"rules": service.rules()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "data" / "holidays.json").write_text(
        json.dumps(HOLIDAYS, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    hol = [h["date"] for h in month_holidays(ym)]
    plan = service.generate_plan(ym, hol)
    plan["download"] = f"data/plan_{ym}.xlsx"
    (out / "data" / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )
    src_xlsx = paths.OUTPUT_DIR / f"plan_{ym}.xlsx"
    if src_xlsx.exists():
        shutil.copy(src_xlsx, out / "data" / f"plan_{ym}.xlsx")

    verify = {vym: service.verify(vym) for vym in VERIFY_YMS}
    (out / "data" / "verify.json").write_text(
        json.dumps(verify, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="site")
    p.add_argument("--ym", default=DEMO_YM)
    args = p.parse_args(argv)
    dest = export(Path(args.out), args.ym)
    print(f"정적 사이트: {dest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
