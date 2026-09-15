# -*- coding: utf-8 -*-
"""경로 설정 — 리포지토리 기준 상대경로로만 다룬다."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"          # 원천 엑셀 + 중간 산출 json
OUTPUT_DIR = ROOT / "output"      # 생성된 엑셀
DOCS_DIR = ROOT / "docs"          # 명세 md

# 원천 데이터
PRODUCTION_LOG_DIR = DATA_DIR / "생산일지"   # 월별 생산일지 xlsx
MENU_SHEET_DIR = DATA_DIR / "식단표"         # 월별 식단표 xlsx

# 중간 산출물
RAW_JSON = DATA_DIR / "raw.json"        # 1단계: 파싱 원본
GROUPS_JSON = DATA_DIR / "groups.json"  # 2단계: 레시피ID 매핑
MASTER_JSON = DATA_DIR / "master.json"  # 3단계: 태깅 완료 마스터
DAYS_JSON = DATA_DIR / "days.json"      # 분석용 일자별 슬롯


def ensure_dirs() -> None:
    for p in (DATA_DIR, OUTPUT_DIR, DOCS_DIR):
        p.mkdir(parents=True, exist_ok=True)
