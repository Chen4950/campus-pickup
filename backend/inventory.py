import csv
import io
import math
import sqlite3
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from .accounts import Username, administrator, current_user, database
from .routing import StationRoutes

router = APIRouter()
CSV_FIELDS = ("username", "code", "shelf", "level", "suffix")
PARCEL_COLUMNS = """
    inventory.id, users.username, code, shelf, level, suffix, status, received_at, closed_at
"""


def initialize_inventory():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS shelf_changes (
                id TEXT PRIMARY KEY,
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                x REAL,
                y REAL,
                anchor TEXT,
                distance REAL
            );
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                code TEXT NOT NULL UNIQUE,
                shelf TEXT NOT NULL,
                level TEXT NOT NULL,
                suffix TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'picked_up', 'discarded')),
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS inventory_owner_status ON inventory(owner_id, status);
            CREATE INDEX IF NOT EXISTS inventory_shelf_status ON inventory(shelf, status);
        """)


def layout_for(request, db):
    base = request.app.state.data["layout"]
    changes = list(db.execute("SELECT * FROM shelf_changes ORDER BY id"))
    disabled = {row["id"] for row in changes if not row["active"]}
    nodes = [dict(node, type="aisle") if node["id"] in disabled else node for node in base["nodes"]]
    edges = list(base["directed_edges"])
    for row in changes:
        if row["anchor"] is None:
            continue
        nodes.append({
            "id": row["id"], "type": "shelf" if row["active"] else "aisle",
            "x": row["x"], "y": row["y"],
        })
        for source, target in ((row["anchor"], row["id"]), (row["id"], row["anchor"])):
            edges.append({"from": source, "to": target, "distance_m": row["distance"]})
    return {**base, "nodes": nodes, "directed_edges": edges}


def active_shelves(layout):
    return [node for node in layout["nodes"] if node["type"] == "shelf"]


def pending_for(db, user_id):
    return [
        dict(row) for row in db.execute("""
            SELECT id, code, shelf, level, suffix FROM inventory
            WHERE owner_id = ? AND status = 'pending' ORDER BY id
        """, (user_id,))
    ]


def plan_for(request, db, start, parcels):
    data = request.app.state.data
    routes = StationRoutes(data["station"], layout_for(request, db))
    return routes.plan(start, [parcel["shelf"] for parcel in parcels])


def normalized_code(code):
    return unicodedata.normalize("NFKC", code).strip().upper()


class ParcelInput(BaseModel):
    username: Username
    code: str = Field(min_length=1, max_length=100)
    shelf: str = Field(min_length=1, max_length=24)
    level: str = Field(pattern=r"^[0-9]{1,2}$")
    suffix: str = Field(pattern=r"^[0-9]{4}$")


class ImportInput(BaseModel):
    csv: str = Field(min_length=1, max_length=150_000)


class ShelfInput(BaseModel):
    id: str = Field(pattern=r"^[A-Z][0-9]{1,3}$")
    x: float = Field(ge=-1000, le=1000, allow_inf_nan=False)
    y: float = Field(ge=-1000, le=1000, allow_inf_nan=False)
    anchor: str = Field(min_length=1, max_length=24)


class ScanInput(BaseModel):
    code: str = Field(min_length=1, max_length=100)


@router.get("/api/parcels/mine")
def my_parcels(user=Depends(current_user)):
    with database() as db:
        return pending_for(db, user["id"])


@router.get("/api/admin/parcels")
def search_parcels(
    username: str = Query("", max_length=32),
    shelf: str = Query("", max_length=24),
    suffix: str = Query("", max_length=4),
    status: str = Query("", pattern=r"^(pending|picked_up|discarded)?$"),
    page: int = Query(1, ge=1, le=2**31),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(administrator),
):
    base = """
        FROM inventory JOIN users ON users.id = inventory.owner_id
        WHERE instr(lower(users.username), lower(?)) > 0
          AND (? = '' OR shelf = ?) AND instr(suffix, ?) > 0
          AND (? = '' OR status = ?)
    """
    params = (username.strip(), shelf, shelf, suffix.strip(), status, status)
    with database() as db:
        db.execute("BEGIN")
        count = db.execute("SELECT COUNT(*) " + base, params).fetchone()[0]
        page = min(page, max(1, (count + page_size - 1) // page_size))
        rows = db.execute(
            "SELECT " + PARCEL_COLUMNS + base + " ORDER BY inventory.id DESC LIMIT ? OFFSET ?",
            (*params, page_size, (page - 1) * page_size),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": count, "page": page, "page_size": page_size}


@router.post("/api/admin/parcels/import", status_code=201)
def import_parcels(payload: ImportInput, request: Request, user=Depends(administrator)):
    reader = csv.DictReader(io.StringIO(payload.csv.lstrip("\ufeff"), newline=""), strict=True)
    try:
        if reader.fieldnames is None or len(reader.fieldnames) != len(CSV_FIELDS) or set(reader.fieldnames) != set(CSV_FIELDS):
            raise HTTPException(422, "CSV 表头须包含 username,code,shelf,level,suffix。")
        records = []
        for row in reader:
            if len(records) >= 1000:
                raise HTTPException(422, "一次最多导入 1000 件包裹。")
            if None in row or any(value is None for value in row.values()):
                raise HTTPException(422, f"CSV 第 {reader.line_num} 行列数有误。")
            values = {name: value.strip() for name, value in row.items()}
            values["shelf"] = values["shelf"].upper()
            values["code"] = normalized_code(values["code"])
            try:
                records.append((reader.line_num, ParcelInput.model_validate(values)))
            except ValidationError as error:
                field = error.errors()[0]["loc"][0]
                raise HTTPException(422, f"CSV 第 {reader.line_num} 行的 {field} 格式有误。") from error
    except csv.Error as error:
        raise HTTPException(422, f"CSV 第 {reader.line_num} 行格式有误。") from error
    if not records:
        raise HTTPException(422, "CSV 没有包裹数据。")

    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        shelves = {node["id"] for node in active_shelves(layout_for(request, db))}
        for line, parcel in records:
            owner = db.execute(
                "SELECT id FROM users WHERE username = ? AND role = 'user'", (parcel.username,),
            ).fetchone()
            if not owner:
                raise HTTPException(422, f"CSV 第 {line} 行的普通用户尚未注册。")
            if parcel.shelf not in shelves:
                raise HTTPException(422, f"CSV 第 {line} 行的货架不存在。")
            try:
                db.execute("""
                    INSERT INTO inventory (owner_id, code, shelf, level, suffix) VALUES (?, ?, ?, ?, ?)
                """, (owner["id"], parcel.code, parcel.shelf, parcel.level, parcel.suffix))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, f"CSV 第 {line} 行包裹码已存在。") from error
    return {"imported": len(records)}


def close_parcel(db, parcel_id, status):
    updated = db.execute("""
        UPDATE inventory SET status = ?, closed_at = ? WHERE id = ? AND status = 'pending'
    """, (status, datetime.now(timezone.utc).isoformat(), parcel_id))
    if not updated.rowcount:
        if db.execute("SELECT id FROM inventory WHERE id = ?", (parcel_id,)).fetchone():
            raise HTTPException(409, "该包裹已出库或丢弃。")
        raise HTTPException(404, "未找到该包裹。")
    return {"id": parcel_id, "status": status}


@router.delete("/api/admin/parcels/{parcel_id}")
def discard_parcel(parcel_id: int, user=Depends(administrator)):
    with database() as db:
        return close_parcel(db, parcel_id, "discarded")


@router.post("/api/admin/pickup/lookup")
def find_scanned_parcel(payload: ScanInput, user=Depends(administrator)):
    with database() as db:
        row = db.execute(
            "SELECT " + PARCEL_COLUMNS + """
            FROM inventory JOIN users ON users.id = inventory.owner_id WHERE code = ?
            """, (normalized_code(payload.code),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "未找到该包裹，请检查面单码。")
    if row["status"] != "pending":
        raise HTTPException(409, "该包裹已出库或丢弃。")
    return dict(row)


@router.post("/api/admin/pickup/{parcel_id}")
def confirm_pickup(parcel_id: int, user=Depends(administrator)):
    with database() as db:
        return close_parcel(db, parcel_id, "picked_up")


@router.get("/api/admin/shelves")
def list_shelves(request: Request, user=Depends(administrator)):
    with database() as db:
        layout = layout_for(request, db)
    return {
        "shelves": active_shelves(layout),
        "anchors": [node for node in layout["nodes"] if node["type"] not in ("verification", "exit")],
    }


@router.post("/api/admin/shelves", status_code=201)
def create_shelf(payload: ShelfInput, request: Request, user=Depends(administrator)):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        nodes = {node["id"]: node for node in layout_for(request, db)["nodes"]}
        existing = nodes.get(payload.id)
        if existing:
            if existing["type"] != "aisle":
                raise HTTPException(409, "该货架编号已存在。")
            if (payload.x, payload.y) != (existing["x"], existing["y"]):
                raise HTTPException(422, "恢复货架时请填写原坐标。")
            db.execute("UPDATE shelf_changes SET active = 1 WHERE id = ?", (payload.id,))
        else:
            anchor = nodes.get(payload.anchor)
            if not anchor or anchor["type"] in ("verification", "exit"):
                raise HTTPException(422, "请选择入口、货架或通道作为连接点。")
            distance = round(math.hypot(payload.x - anchor["x"], payload.y - anchor["y"]), 2)
            if not distance:
                raise HTTPException(422, "货架坐标需要与连接点不同。")
            db.execute(
                "INSERT INTO shelf_changes VALUES (?, 1, ?, ?, ?, ?)",
                (payload.id, payload.x, payload.y, payload.anchor, distance),
            )
    return {"id": payload.id}


@router.delete("/api/admin/shelves/{shelf}")
def delete_shelf(shelf: str, request: Request, user=Depends(administrator)):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if shelf not in {node["id"] for node in active_shelves(layout_for(request, db))}:
            raise HTTPException(404, "找不到该货架。")
        if db.execute("SELECT 1 FROM inventory WHERE shelf = ? AND status = 'pending' LIMIT 1", (shelf,)).fetchone():
            raise HTTPException(409, "货架还有待取件包裹。")
        db.execute("""
            INSERT INTO shelf_changes (id, active) VALUES (?, 0)
            ON CONFLICT(id) DO UPDATE SET active = 0
        """, (shelf,))
    return {"id": shelf}
