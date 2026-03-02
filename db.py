import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "cs_hub.db"))

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT NOT NULL,
    body             TEXT,
    summary          TEXT,
    status           TEXT DEFAULT 'open',     -- open / in_progress / done / closed
    priority         TEXT DEFAULT 'normal',   -- low / normal / high / urgent
    assignee         TEXT,                    -- 金子 / 和田 / 福江 / NULL=未担当
    due_date         DATE,
    chatwork_room_id TEXT,
    chatwork_message_id TEXT,
    sender_name      TEXT,
    sender_account_id TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at     DATETIME,
    reminded_2days   INTEGER DEFAULT 0,
    reminded_1day    INTEGER DEFAULT 0,
    reminded_today   INTEGER DEFAULT 0,
    unread_reply     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS task_threads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id             INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    chatwork_message_id TEXT,
    sender_name         TEXT,
    sender_account_id   TEXT,
    body                TEXT,
    direction           TEXT DEFAULT 'inbound',  -- inbound / outbound
    sent_at             DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recurring_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    template        TEXT,
    assignee        TEXT,
    day_of_month    INTEGER DEFAULT 1,
    chatwork_room_id TEXT,
    active          INTEGER DEFAULT 1,
    last_generated  DATE
);

CREATE TABLE IF NOT EXISTS room_state (
    room_id        TEXT PRIMARY KEY,
    last_message_id TEXT,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS processed_messages (
    chatwork_message_id TEXT PRIMARY KEY,
    processed_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        # マイグレーション：カラム追加（既存DBに対応）
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN chatwork_room_name TEXT")
        except Exception:
            pass
        # マイグレーション：unread_replyカラム追加
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN unread_reply INTEGER DEFAULT 0")
        except Exception:
            pass
        # 既存タスクのchatwork_message_idをprocessed_messagesに同期（重複防止）
        conn.execute("""
            INSERT OR IGNORE INTO processed_messages (chatwork_message_id)
            SELECT chatwork_message_id FROM tasks WHERE chatwork_message_id IS NOT NULL
        """)

# ─── Tasks ────────────────────────────────────────────────────

def get_tasks(assignee=None, status=None, priority=None, search=None):
    q = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if assignee == "未担当":
        q += " AND assignee IS NULL"
    elif assignee:
        q += " AND assignee = ?"
        params.append(assignee)
    if status:
        q += " AND status = ?"
        params.append(status)
    if priority:
        q += " AND priority = ?"
        params.append(priority)
    if search:
        q += " AND (title LIKE ? OR summary LIKE ? OR body LIKE ?)"
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    q += " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, due_date ASC NULLS LAST, created_at DESC"
    with db() as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]

def get_task(task_id: int):
    with db() as conn:
        r = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(r) if r else None

def create_task(data: dict) -> int:
    fields = ["title", "body", "summary", "status", "priority", "assignee",
              "due_date", "chatwork_room_id", "chatwork_message_id",
              "sender_name", "sender_account_id", "chatwork_room_name"]
    vals = {k: data.get(k) for k in fields if k in data}
    cols = ", ".join(vals.keys())
    placeholders = ", ".join(["?"] * len(vals))
    with db() as conn:
        cur = conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", list(vals.values()))
        return cur.lastrowid

def update_task(task_id: int, data: dict):
    allowed = ["title", "body", "summary", "status", "priority", "assignee",
               "due_date", "reminded_2days", "reminded_1day", "reminded_today",
               "completed_at", "unread_reply"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = "CURRENT_TIMESTAMP"
    set_clause = ", ".join(f"{k} = ?" for k in updates if k != "updated_at")
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    vals = [v for k, v in updates.items() if k != "updated_at"]
    vals.append(task_id)
    with db() as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", vals)

def delete_task(task_id: int):
    with db() as conn:
        task = conn.execute("SELECT chatwork_message_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task and task["chatwork_message_id"]:
            conn.execute(
                "INSERT OR IGNORE INTO processed_messages (chatwork_message_id) VALUES (?)",
                (task["chatwork_message_id"],)
            )
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

def find_task_by_message_id(message_id: str, room_id: str) -> dict | None:
    """引用元メッセージIDからタスクを特定（タスク本体 or スレッド内を検索）"""
    with db() as conn:
        # タスク本体のchatwork_message_idと一致
        r = conn.execute(
            "SELECT * FROM tasks WHERE chatwork_message_id = ? AND chatwork_room_id = ?",
            (message_id, room_id)
        ).fetchone()
        if r:
            return dict(r)
        # スレッド内のメッセージIDと一致するタスクを検索
        r = conn.execute(
            "SELECT t.* FROM tasks t "
            "JOIN task_threads th ON th.task_id = t.id "
            "WHERE th.chatwork_message_id = ? AND t.chatwork_room_id = ?",
            (message_id, room_id)
        ).fetchone()
        return dict(r) if r else None

def is_message_processed(message_id: str) -> bool:
    with db() as conn:
        r = conn.execute("SELECT 1 FROM processed_messages WHERE chatwork_message_id = ?", (message_id,)).fetchone()
        if r:
            return True
        # processed_messagesになくても既存タスクにあれば処理済みとみなす
        r2 = conn.execute("SELECT 1 FROM tasks WHERE chatwork_message_id = ?", (message_id,)).fetchone()
        if r2:
            conn.execute("INSERT OR IGNORE INTO processed_messages (chatwork_message_id) VALUES (?)", (message_id,))
            return True
        return False

def mark_message_processed(message_id: str):
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO processed_messages (chatwork_message_id) VALUES (?)", (message_id,))

def bulk_update_tasks(task_ids: list, data: dict):
    allowed = ["assignee", "priority", "due_date", "status"]
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    placeholders = ", ".join(["?"] * len(task_ids))
    vals = list(updates.values()) + task_ids
    with db() as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id IN ({placeholders})", vals)

# ─── Threads ──────────────────────────────────────────────────

def get_threads(task_id: int):
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM task_threads WHERE task_id = ? ORDER BY sent_at ASC",
            (task_id,)
        ).fetchall()]

def add_thread(task_id: int, data: dict) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO task_threads (task_id, chatwork_message_id, sender_name, sender_account_id, body, direction) VALUES (?,?,?,?,?,?)",
            (task_id, data.get("chatwork_message_id"), data.get("sender_name"),
             data.get("sender_account_id"), data.get("body"), data.get("direction", "inbound"))
        )
        # 受信メッセージなら未読フラグを立てる
        if data.get("direction", "inbound") == "inbound":
            conn.execute("UPDATE tasks SET unread_reply = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (task_id,))
        return cur.lastrowid

# ─── Room state ───────────────────────────────────────────────

def get_last_message_id(room_id: str):
    with db() as conn:
        r = conn.execute("SELECT last_message_id FROM room_state WHERE room_id = ?", (room_id,)).fetchone()
        return r["last_message_id"] if r else None

def set_last_message_id(room_id: str, message_id: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO room_state (room_id, last_message_id) VALUES (?,?) "
            "ON CONFLICT(room_id) DO UPDATE SET last_message_id=excluded.last_message_id, updated_at=CURRENT_TIMESTAMP",
            (room_id, message_id)
        )

# ─── Dashboard ────────────────────────────────────────────────

def get_dashboard_stats():
    with db() as conn:
        total     = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done      = conn.execute("SELECT COUNT(*) FROM tasks WHERE status IN ('done','closed')").fetchone()[0]
        inbound   = conn.execute("SELECT COUNT(*) FROM tasks WHERE chatwork_message_id IS NOT NULL").fetchone()[0]
        outbound  = conn.execute("SELECT COUNT(*) FROM tasks WHERE chatwork_message_id IS NULL").fetchone()[0]

        # アラート
        unassigned = conn.execute(
            "SELECT * FROM tasks WHERE assignee IS NULL AND status NOT IN ('done','closed') ORDER BY created_at ASC"
        ).fetchall()
        overdue = conn.execute(
            "SELECT * FROM tasks WHERE due_date < date('now') AND status NOT IN ('done','closed') ORDER BY due_date ASC"
        ).fetchall()
        no_reply = conn.execute(
            "SELECT t.* FROM tasks t "
            "WHERE t.status NOT IN ('done','closed') "
            "AND t.chatwork_room_id IS NOT NULL "
            "AND datetime(t.updated_at) < datetime('now','-2 hours') "
            "AND NOT EXISTS (SELECT 1 FROM task_threads tt WHERE tt.task_id=t.id AND tt.direction='inbound' AND datetime(tt.sent_at) > datetime('now','-2 hours')) "
            "ORDER BY t.updated_at ASC"
        ).fetchall()

        # 担当者パフォーマンス
        staff = []
        for name in ["金子", "和田", "福江"]:
            holding = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assignee=? AND status NOT IN ('done','closed')", (name,)
            ).fetchone()[0]
            done_month = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE assignee=? AND status IN ('done','closed') AND completed_at >= date('now','start of month')", (name,)
            ).fetchone()[0]
            avg_days_row = conn.execute(
                "SELECT AVG(julianday(completed_at)-julianday(created_at)) FROM tasks "
                "WHERE assignee=? AND status IN ('done','closed') AND completed_at IS NOT NULL", (name,)
            ).fetchone()[0]
            avg_days = round(avg_days_row, 1) if avg_days_row else None
            staff.append({"name": name, "holding": holding, "done_month": done_month, "avg_days": avg_days})

        return {
            "kpi": {
                "total": total,
                "done": done,
                "inbound": inbound,
                "outbound": outbound,
                "completion_rate": round(done / total * 100) if total else 0
            },
            "staff": staff,
            "alerts": {
                "unassigned": [dict(r) for r in unassigned],
                "overdue": [dict(r) for r in overdue],
                "no_reply": [dict(r) for r in no_reply],
            }
        }

# ─── Settings ────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with db() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )

# ─── Recurring ────────────────────────────────────────────────

def get_recurring():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM recurring_tasks ORDER BY day_of_month, title").fetchall()]

def create_recurring(data: dict) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO recurring_tasks (title, template, assignee, day_of_month, chatwork_room_id) VALUES (?,?,?,?,?)",
            (data["title"], data.get("template"), data.get("assignee"),
             data.get("day_of_month", 1), data.get("chatwork_room_id"))
        )
        return cur.lastrowid

def update_recurring(rec_id: int, data: dict):
    allowed = ["title", "template", "assignee", "day_of_month", "chatwork_room_id", "active"]
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with db() as conn:
        conn.execute(f"UPDATE recurring_tasks SET {set_clause} WHERE id = ?", list(updates.values()) + [rec_id])

def delete_recurring(rec_id: int):
    with db() as conn:
        conn.execute("DELETE FROM recurring_tasks WHERE id = ?", (rec_id,))
