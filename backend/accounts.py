import hashlib
import secrets
import sqlite3
from contextlib import closing, contextmanager
from time import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Annotated

from .data import database_path

router = APIRouter(prefix="/api/auth")
COOKIE = "pickup_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
Username = Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[\w.-]+$")]
NewPassword = Annotated[str, Field(min_length=8, max_length=128)]


@contextmanager
def database():
    with closing(sqlite3.connect(database_path())) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        yield db


def password_hash(password, salt=None):
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=3, maxmem=64 * 1024**2)
    return f"scrypt:{salt.hex()}:{digest.hex()}"


def password_matches(password, stored):
    salt = bytes.fromhex(stored.split(":")[1])
    return secrets.compare_digest(password_hash(password, salt), stored)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def initialize_accounts():
    with database() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        """)
        if not db.execute("SELECT 1 FROM users WHERE username = 'admin'").fetchone():
            db.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES ('admin', ?, 'admin')",
                (password_hash("admin"),),
            )


def create_session(db, user_id, request, response):
    token = secrets.token_urlsafe(32)
    now = int(time())
    db.execute("DELETE FROM sessions WHERE expires_at <= ? OR token_hash = ?", (now, session_key(request)))
    db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash(token), user_id, now + SESSION_SECONDS))
    response.set_cookie(
        COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
        secure=request.url.scheme == "https", samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


def session_key(request):
    return token_hash(request.cookies.get(COOKIE, ""))


def current_user(request: Request):
    with database() as db:
        user = db.execute("""
            SELECT users.id, username, role FROM sessions JOIN users ON users.id = user_id
            WHERE token_hash = ? AND expires_at > ?
        """, (session_key(request), int(time()))).fetchone()
    if not user:
        raise HTTPException(401, "请先登录。")
    return user


def administrator(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "此功能仅限管理员。")
    return user


def profile(user):
    return {"username": user["username"], "role": user["role"]}


class Credentials(BaseModel):
    username: Username
    password: str = Field(min_length=1, max_length=128)


class Registration(Credentials):
    password: NewPassword


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: NewPassword


@router.post("/register", status_code=201)
def register(payload: Registration, request: Request, response: Response):
    with database() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, 'user')",
            (payload.username, password_hash(payload.password)),
        )
        if not cursor.rowcount:
            raise HTTPException(409, "该用户名已注册。")
        create_session(db, cursor.lastrowid, request, response)
    return {"username": payload.username, "role": "user"}


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response):
    with database() as db:
        user = db.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
        if not user:
            password_hash(payload.password)
        if not user or not password_matches(payload.password, user["password_hash"]):
            raise HTTPException(401, "用户名或密码错误。")
        db.execute("BEGIN IMMEDIATE")
        latest = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if latest["password_hash"] != user["password_hash"]:
            raise HTTPException(401, "密码已更新，请重新登录。")
        create_session(db, user["id"], request, response)
    return profile(user)


@router.get("/me")
def me(response: Response, user=Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return profile(user)


@router.post("/logout")
def logout(request: Request, response: Response):
    with database() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (session_key(request),))
    response.delete_cookie(COOKIE, httponly=True, secure=request.url.scheme == "https", samesite="strict")
    return {"ok": True}


@router.post("/password")
def change_password(payload: PasswordChange, request: Request, response: Response, user=Depends(current_user)):
    with database() as db:
        existing = db.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
        if not password_matches(payload.current_password, existing):
            raise HTTPException(422, "当前密码错误。")
        updated = db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ? AND password_hash = ?",
            (password_hash(payload.new_password), user["id"], existing),
        )
        if not updated.rowcount:
            raise HTTPException(409, "密码已更新，请重新登录。")
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        create_session(db, user["id"], request, response)
    return {"ok": True}
