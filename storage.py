# storage.py — 資料庫層（SQLite 本機 / Supabase 雲端雙模式）
#
# 本機開發  → 不設 SUPABASE_URL，自動使用本機 SQLite
# Streamlit Cloud → 在 Secrets 設定 SUPABASE_URL + SUPABASE_ANON_KEY，自動切換至 Supabase
import json
import os
import random
import sqlite3
import string
from datetime import datetime
from pathlib import Path

import streamlit as st


# ══════════════════════════════════════════════════════════════════════════════
# 後端偵測
# ══════════════════════════════════════════════════════════════════════════════

def _use_supabase() -> bool:
    try:
        return bool(st.secrets.get("SUPABASE_URL"))
    except Exception:
        return False


@st.cache_resource
def _sb():
    """回傳 Supabase client（快取，整個 session 只建立一次）"""
    from supabase import create_client
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_ANON_KEY"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# SQLite 設定（本機）
# ══════════════════════════════════════════════════════════════════════════════

_data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "VolleyTracker"
_data_dir.mkdir(parents=True, exist_ok=True)
DB_PATH = _data_dir / "volley_data.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _parse(row) -> dict:
    d = dict(row)
    d["players"] = json.loads(d["players"])
    d["logs"]    = json.loads(d["logs"])
    return d


# ══════════════════════════════════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════════════════════════════════

def init_db() -> None:
    """本機模式下建立資料表；Supabase 模式下資料表已在雲端建立（見 supabase_setup.sql）"""
    if _use_supabase():
        return
    db = _conn()
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            code       TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_code   TEXT    NOT NULL,
            match_name  TEXT    NOT NULL,
            players     TEXT    NOT NULL,
            logs        TEXT    NOT NULL,
            current_set INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    db.commit()
    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 代碼產生
# ══════════════════════════════════════════════════════════════════════════════

def _gen_code(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ══════════════════════════════════════════════════════════════════════════════
# 使用者
# ══════════════════════════════════════════════════════════════════════════════

def user_exists(code: str) -> bool:
    code = code.upper().strip()
    if _use_supabase():
        r = _sb().table("users").select("code").eq("code", code).execute()
        return bool(r.data)
    db = _conn()
    row = db.execute("SELECT code FROM users WHERE code = ?", (code,)).fetchone()
    db.close()
    return row is not None


def create_user() -> str:
    now = datetime.now().isoformat()
    last_exc: Exception | None = None
    for _ in range(30):
        code = _gen_code()
        try:
            if _use_supabase():
                _sb().table("users").insert({"code": code, "created_at": now}).execute()
                return code
            else:
                db = _conn()
                db.execute("INSERT INTO users (code, created_at) VALUES (?, ?)", (code, now))
                db.commit()
                db.close()
                return code
        except Exception as e:
            last_exc = e
            continue
    raise RuntimeError(f"無法產生唯一代碼，請稍後再試。原因：{last_exc}")


# ══════════════════════════════════════════════════════════════════════════════
# 比賽 CRUD
# ══════════════════════════════════════════════════════════════════════════════

def get_user_matches(user_code: str) -> list[dict]:
    user_code = user_code.upper().strip()
    if _use_supabase():
        r = _sb().table("matches").select("*").eq("user_code", user_code).order("created_at", desc=True).execute()
        return r.data or []
    db = _conn()
    rows = db.execute(
        "SELECT * FROM matches WHERE user_code = ? ORDER BY created_at DESC", (user_code,)
    ).fetchall()
    db.close()
    return [_parse(row) for row in rows]


def get_match(match_id) -> dict | None:
    if _use_supabase():
        r = _sb().table("matches").select("*").eq("id", match_id).execute()
        return r.data[0] if r.data else None
    db = _conn()
    row = db.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    db.close()
    return _parse(row) if row else None


def create_match(user_code: str, match_name: str,
                 players: list, logs: list, current_set: int = 1):
    now = datetime.now().isoformat()
    user_code = user_code.upper().strip()
    if _use_supabase():
        payload = {
            "user_code": user_code, "match_name": match_name,
            "players": players, "logs": logs,
            "current_set": current_set, "created_at": now, "updated_at": now,
        }
        r = _sb().table("matches").insert(payload).execute()
        return r.data[0]["id"]
    db = _conn()
    cur = db.execute(
        "INSERT INTO matches (user_code,match_name,players,logs,current_set,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (user_code, match_name,
         json.dumps(players, ensure_ascii=False),
         json.dumps(logs,    ensure_ascii=False),
         current_set, now, now),
    )
    mid = cur.lastrowid
    db.commit()
    db.close()
    return mid


def update_match(match_id, players: list, logs: list, current_set: int) -> None:
    now = datetime.now().isoformat()
    if _use_supabase():
        _sb().table("matches").update({
            "players": players, "logs": logs,
            "current_set": current_set, "updated_at": now,
        }).eq("id", match_id).execute()
        return
    db = _conn()
    db.execute(
        "UPDATE matches SET players=?,logs=?,current_set=?,updated_at=? WHERE id=?",
        (json.dumps(players, ensure_ascii=False),
         json.dumps(logs,    ensure_ascii=False),
         current_set, now, match_id),
    )
    db.commit()
    db.close()


def rename_match(match_id, new_name: str) -> None:
    now = datetime.now().isoformat()
    if _use_supabase():
        _sb().table("matches").update({"match_name": new_name, "updated_at": now}).eq("id", match_id).execute()
        return
    db = _conn()
    db.execute("UPDATE matches SET match_name=?,updated_at=? WHERE id=?", (new_name, now, match_id))
    db.commit()
    db.close()


def delete_match(match_id) -> None:
    if _use_supabase():
        _sb().table("matches").delete().eq("id", match_id).execute()
        return
    db = _conn()
    db.execute("DELETE FROM matches WHERE id=?", (match_id,))
    db.commit()
    db.close()
