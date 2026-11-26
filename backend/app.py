from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .data import PROJECT, load_station_data
from .forecast import SHANGHAI, StationForecast
from .ocr import MAX_IMAGE_BYTES, ScreenshotReader, candidates_from_text
from .routing import StationRoutes


class RouteRequest(BaseModel):
    start: str = Field(max_length=24)
    shelves: list[str] = Field(max_length=40)
    closed_edges: list[tuple[str, str]] = Field(default_factory=list, max_length=50)


class TripEstimate(BaseModel):
    distance_m: float = Field(ge=0, le=10000, allow_inf_nan=False)
    to_verification_m: float = Field(ge=0, le=10000, allow_inf_nan=False)
    parcel_count: int = Field(ge=0, le=40)

    @model_validator(mode="after")
    def check_distance(self):
        if self.to_verification_m > self.distance_m:
            raise ValueError("到核验点的距离须在总路线距离以内。")
        return self


class ForecastRequest(BaseModel):
    day: date
    earliest: time
    latest: time
    trip: TripEstimate | None = None


@asynccontextmanager
async def lifespan(application):
    data = load_station_data()
    application.state.data = data
    application.state.routes = StationRoutes(data["station"], data["layout"])
    application.state.forecast = StationForecast(data["station"], data["queue"])
    application.state.reader = ScreenshotReader()
    yield


app = FastAPI(title="校园驿站取件助手", lifespan=lifespan)


@app.get("/api/station")
def station_details(request: Request):
    data = request.app.state.data
    parcels = {row["parcel_id"]: row for row in data["parcels"]}
    scenario = next(case for case in data["route_test_scenarios"] if case["id"] == "scattered_multi_pickup")
    demo = []
    for parcel_id in scenario["parcel_ids_in_input_order"]:
        parcel = parcels[parcel_id]
        shelf, level, suffix = (parcel[name] for name in ("shelf_id", "level", "tracking_suffix"))
        demo.append({"code": f"{shelf}-{level}-{suffix}", "shelf": shelf, "level": level, "suffix": suffix})
    now = datetime.now(SHANGHAI)
    return {
        "station": data["station"],
        "layout": data["layout"],
        "demo_parcels": demo,
        "data_type": data["meta"]["data_type"],
        "today": now.date().isoformat(),
        "tomorrow": (now.date() + timedelta(days=1)).isoformat(),
        "current_time": now.strftime("%H:%M"),
    }


@app.post("/api/routes")
def plan_route(payload: RouteRequest, request: Request):
    try:
        return request.app.state.routes.plan(payload.start, payload.shelves, payload.closed_edges)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/forecasts")
def forecast_times(payload: ForecastRequest, request: Request):
    try:
        return request.app.state.forecast.recommendations(
            payload.day, payload.earliest.replace(tzinfo=None), payload.latest.replace(tzinfo=None),
            payload.trip.model_dump() if payload.trip else None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/forecasts/evaluation")
def evaluate_forecast(request: Request):
    split = date.fromisoformat(request.app.state.data["meta"]["suggested_holdout_start"])
    return {"holdout_start": split.isoformat(), **request.app.state.forecast.backtest(split)}


@app.post("/api/ocr")
async def recognize_screenshot(request: Request):
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
    return {"candidates": candidates_from_text(lines, request.app.state.routes.shelves)}


if (PROJECT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=PROJECT / "dist", html=True), name="frontend")
