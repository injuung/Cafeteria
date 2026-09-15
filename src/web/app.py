# -*- coding: utf-8 -*-
"""키즈락 식단표 웹 화면.

    python -m src.web
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.web import service

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="키즈락 식단표", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class PlanRequest(BaseModel):
    ym: str = Field(..., examples=["2026-11"])
    holidays: list[str] = Field(default_factory=list)


class VerifyRequest(BaseModel):
    ym: str = Field(..., examples=["2026-07"])


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def api_meta():
    return service.meta()


@app.get("/api/calendar")
def api_calendar(
    ym: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    holidays: str | None = Query(None, description="쉼표 구분 ISO 날짜. 생략하면 공휴일만."),
):
    hol = None if holidays is None else [h for h in holidays.split(",") if h]
    try:
        return service.calendar_view(ym, hol)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/plan")
def api_plan(body: PlanRequest):
    try:
        return service.generate_plan(body.ym, body.holidays)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(500, f"원천 데이터가 없습니다: {exc}") from exc


@app.get("/api/rules")
def api_rules():
    return {"rules": service.rules()}


@app.post("/api/verify")
def api_verify(body: VerifyRequest):
    try:
        return service.verify(body.ym)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/files/{name}")
def api_file(name: str):
    try:
        path = service.output_file(name)
    except FileNotFoundError:
        raise HTTPException(404, "파일이 없습니다. 초안을 먼저 만들어 주세요.")
    display = name
    if name.startswith("plan_") and name.endswith(".xlsx"):
        ym = name[5:-5]
        try:
            display = f"{int(ym[5:7])}월_생산일지_초안.xlsx"
        except (ValueError, IndexError):
            display = name
    encoded = quote(display)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=display,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("src.web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
