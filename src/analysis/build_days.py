# -*- coding: utf-8 -*-
"""
분석용 일자별 슬롯 테이블(days.json) 생성.

원천은 생산일지 파싱 결과(raw.json)다. 식단표 엑셀을 다시 읽지 않는 이유는
생산일지 쪽에 '구분'(밥/국/메인/반찬1~3) 컬럼이 이미 있어 슬롯이 확정적이기 때문이다.

    python -m src.analysis.build_days
"""
from __future__ import annotations

import collections
import json
import sys

from src.config import paths
from src.domain.repository import Repository

SUB_SLOTS = {"서브1", "서브2"}


def build(line: str = "유아") -> list:
    repo = Repository()
    by_day = collections.defaultdict(lambda: collections.defaultdict(list))
    for d, ln, slot, rid, name in repo.history:
        if ln != line or not slot:
            continue
        key = "서브" if slot in SUB_SLOTS else slot
        by_day[d][key].append(rid)
    return [{"date": d, "slots": dict(by_day[d])} for d in sorted(by_day)]


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    line = argv[0] if argv else "유아"
    rows = build(line)
    paths.ensure_dirs()
    paths.DAYS_JSON.write_text(
        json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"days.json 생성 — {len(rows)}일 ({line} 라인)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
