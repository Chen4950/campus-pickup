from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .accounts import current_user, database, initialize_accounts, router as accounts_router
from .data import PROJECT, load_station_data
from .forecast import SHANGHAI, StationForecast
from .inventory import initialize_inventory, layout_for, pending_for, plan_for, router as inventory_router
from .ocr import MAX_IMAGE_BYTES, ScreenshotReader, candidates_from_text


class RouteRequest(BaseModel):
    start: str = Field(max_length=24)
    excluded_ids: set[int] = Field(default_factory=set)


class ForecastRequest(BaseModel):
    day: date
    earliest: time
    latest: time
    excluded_ids: set[int] = Field(default_factory=set)


@asynccontextmanager
async def lifespan(application):
    data = load_station_data()
    initialize_accounts()
    initialize_inventory()
    application.state.data = data
    application.state.forecast = StationForecast(data["station"], data["queue"])
    application.state.reader = ScreenshotReader()
    yield


app = FastAPI(title="校园驿站取件助手", lifespan=lifespan)
app.include_router(accounts_router)
app.include_router(inventory_router)


@app.middleware("http")
async def api_headers(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if request.method != "GET" and request.headers.get("sec-fetch-site") == "cross-site":
            return Response(status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
    return await call_next(request)


@app.get("/api/station")
def station_details(request: Request, user=Depends(current_user)):
    data = request.app.state.data
    with database() as db:
        layout = layout_for(request, db)
    now = datetime.now(SHANGHAI)
    return {
        "station": data["station"],
        "layout": layout,
        "data_type": data["meta"]["data_type"],
        "today": now.date().isoformat(),
        "tomorrow": (now.date() + timedelta(days=1)).isoformat(),
        "current_time": now.strftime("%H:%M"),
    }


@app.post("/api/routes")
def plan_route(payload: RouteRequest, request: Request, user=Depends(current_user)):
    try:
        with database() as db:
            db.execute("BEGIN")
            parcels = [row for row in pending_for(db, user["id"]) if row["id"] not in payload.excluded_ids]
            return plan_for(request, db, payload.start, parcels)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/forecasts")
def forecast_times(payload: ForecastRequest, request: Request, user=Depends(current_user)):
    trip = None
    with database() as db:
        db.execute("BEGIN")
        parcels = [row for row in pending_for(db, user["id"]) if row["id"] not in payload.excluded_ids]
        if parcels:
            try:
                start = request.app.state.data["station"]["entry_node"]
                route = plan_for(request, db, start, parcels)
                if not route["unreachable_shelves"]:
                    trip = dict(route, parcel_count=len(parcels))
            except ValueError:
                pass
    try:
        return request.app.state.forecast.recommendations(
            payload.day, payload.earliest.replace(tzinfo=None), payload.latest.replace(tzinfo=None),
            trip,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/forecasts/evaluation")
def evaluate_forecast(request: Request, user=Depends(current_user)):
    split = date.fromisoformat(request.app.state.data["meta"]["suggested_holdout_start"])
    return {"holdout_start": split.isoformat(), **request.app.state.forecast.backtest(split)}


@app.post("/api/ocr")
async def recognize_screenshot(request: Request, user=Depends(current_user)):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="图片超过 6 MB，请裁剪后重试。")
        raw.extend(chunk)
    try:
        lines = await run_in_threadpool(request.app.state.reader.read, raw)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    with database() as db:
        shelves = {node["id"] for node in layout_for(request, db)["nodes"] if node["type"] == "shelf"}
    return {"candidates": candidates_from_text(lines, shelves)}


if (PROJECT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=PROJECT / "dist", html=True), name="frontend")
