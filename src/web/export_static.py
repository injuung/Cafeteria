# -*- coding: utf-8 -*-
"""GitHub Pages 용 정적 사이트를 만든다.

    python -m src.web.export_static --out site
"""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from src.config import paths
from src.web import service
from src.web.holidays import HOLIDAYS

STATIC = Path(__file__).resolve().parent / "static"


def _runtime_zip(out: Path) -> None:
    root = paths.ROOT
    dest = out / "py" / "runtime.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in (root / "src").rglob("*.py"):
            zf.write(p, p.relative_to(root).as_posix())
        for name in ("master.json", "raw.json", "groups.json"):
            zf.write(root / "data" / name, f"data/{name}")


def export(out: Path) -> Path:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    (out / "data").mkdir()
    (out / ".nojekyll").write_text("", encoding="utf-8")

    shutil.copy(STATIC / "index.html", out / "index.html")
    for name in ("styles.css", "app.js", "py-worker.js"):
        shutil.copy(STATIC / name, out / "static" / name)

    meta = service.meta()
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
    _runtime_zip(out)
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="site")
    args = p.parse_args(argv)
    dest = export(Path(args.out))
    print(f"정적 사이트: {dest.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
