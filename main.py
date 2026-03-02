import os
import asyncio
from datetime import datetime, date, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import db
import chatwork as cw

load_dotenv()

# ─── 設定 ─────────────────────────────────────────────────────

API_TOKEN        = os.getenv("CHATWORK_API_TOKEN", "")
HUB_ACCOUNT_ID   = os.getenv("CHATWORK_HUB_ACCOUNT_ID", "")
ROOM_IDS         = [r.strip() for r in os.getenv("CHATWORK_ROOM_IDS", "").split(",") if r.strip()]
AI_ENABLED        = os.getenv("AI_SUMMARY_ENABLED", "false").lower() == "true"
ANTHROPIC_KEY     = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_ASSIGNEE  = os.getenv("DEFAULT_ASSIGNEE", "")

STAFF_ROOMS = {
    "金子": os.getenv("STAFF_KANEKO_ROOM_ID", ""),
    "和田": os.getenv("STAFF_WADA_ROOM_ID", ""),
    "福江": os.getenv("STAFF_FUKUE_ROOM_ID", ""),
}

cw_client = cw.ChatworkClient(API_TOKEN) if API_TOKEN else None

# ─── ルーム自動検知 ───────────────────────────────────────────

async def get_active_rooms() -> list[dict]:
    """CS_HUBくんが参加しているグループルームを自動取得（room_id, name）"""
    if not cw_client:
        return [{"room_id": r, "name": r} for r in ROOM_IDS]
    try:
        rooms = await cw_client.get_rooms()
        return [{"room_id": str(r["room_id"]), "name": r.get("name", str(r["room_id"]))}
                for r in rooms if r.get("type") == "group"]
    except Exception:
        return [{"room_id": r, "name": r} for r in ROOM_IDS]

async def resolve_dm_room(account_id: str) -> str:
    """ChatworkアカウントIDからDM用ルームIDを自動解決"""
    if not cw_client or not account_id:
        return ""
    try:
        rooms = await cw_client.get_rooms()
        for room in rooms:
            if room.get("type") != "direct":
                continue
            members = await cw_client.get_room_members(str(room["room_id"]))
            if any(str(m.get("account_id", "")) == str(account_id) for m in members):
                return str(room["room_id"])
    except Exception:
        pass
    return ""

def get_staff_room(name: str) -> str:
    """担当者のDMルームIDをDBから取得（アカウントIDから解決済みのものを返す）"""
    return db.get_setting(f"staff_room_{name}") or STAFF_ROOMS.get(name, "")

# ─── AI要約 ───────────────────────────────────────────────────

async def generate_summary(text: str) -> str:
    if not AI_ENABLED or not ANTHROPIC_KEY:
        return text[:30]
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": f"以下を30文字以内の日本語で要約してください。要約のみ返答してください。\n\n{text}"
            }]
        )
        return msg.content[0].text[:30]
    except Exception:
        return text[:30]

# ─── Chatworkポーリング ───────────────────────────────────────

async def poll_chatwork():
    if not cw_client or not HUB_ACCOUNT_ID:
        return
    active_rooms = await get_active_rooms()
    for room_info in active_rooms:
        room_id   = room_info["room_id"]
        room_name = room_info["name"]
        try:
            messages = await cw_client.get_messages(room_id, force=1)
            if not messages:
                continue

            last_id = db.get_last_message_id(room_id)
            new_messages = []
            for m in messages:
                mid = str(m["message_id"])
                if last_id is None or int(mid) > int(last_id):
                    new_messages.append(m)

            if not new_messages:
                continue

            for m in new_messages:
                body = m.get("body", "")
                if cw.parse_mentions(body, HUB_ACCOUNT_ID):
                    clean = cw.clean_body(body)
                    summary = await generate_summary(clean)
                    task_id = db.create_task({
                        "title": summary,
                        "body": clean,
                        "summary": summary,
                        "assignee": DEFAULT_ASSIGNEE or None,
                        "chatwork_room_id": room_id,
                        "chatwork_room_name": room_name,
                        "chatwork_message_id": str(m["message_id"]),
                        "sender_name": m.get("account", {}).get("name", ""),
                        "sender_account_id": str(m.get("account", {}).get("account_id", "")),
                    })
                    # スレッドの初期メッセージとして保存
                    db.add_thread(task_id, {
                        "chatwork_message_id": str(m["message_id"]),
                        "sender_name": m.get("account", {}).get("name", ""),
                        "sender_account_id": str(m.get("account", {}).get("account_id", "")),
                        "body": clean,
                        "direction": "inbound",
                    })
                else:
                    # 既存タスクへの返信かチェック
                    existing = db.get_tasks()
                    for task in existing:
                        if task.get("chatwork_room_id") == room_id and task.get("status") not in ("done", "closed"):
                            db.add_thread(task["id"], {
                                "chatwork_message_id": str(m["message_id"]),
                                "sender_name": m.get("account", {}).get("name", ""),
                                "sender_account_id": str(m.get("account", {}).get("account_id", "")),
                                "body": m.get("body", ""),
                                "direction": "inbound",
                            })
                            db.update_task(task["id"], {})  # updated_at更新

            max_id = str(max(int(str(m["message_id"])) for m in new_messages))
            db.set_last_message_id(room_id, max_id)
        except Exception as e:
            print(f"[poll] room {room_id} error: {e}")

# ─── リマインド送信 ───────────────────────────────────────────

async def send_reminders():
    if not cw_client:
        return
    today = date.today()
    tasks = db.get_tasks()
    for task in tasks:
        if task["status"] in ("done", "closed") or not task["due_date"] or not task["assignee"]:
            continue
        due = date.fromisoformat(task["due_date"])
        days_left = (due - today).days
        room_id = get_staff_room(task["assignee"])
        if not room_id:
            continue

        try:
            if days_left == 2 and not task["reminded_2days"]:
                await cw_client.send_message(room_id, cw.make_reminder_message(
                    task["title"], task["due_date"], 2, task["id"]))
                db.update_task(task["id"], {"reminded_2days": 1})
            elif days_left == 1 and not task["reminded_1day"]:
                await cw_client.send_message(room_id, cw.make_reminder_message(
                    task["title"], task["due_date"], 1, task["id"]))
                db.update_task(task["id"], {"reminded_1day": 1})
            elif days_left == 0 and not task["reminded_today"]:
                await cw_client.send_message(room_id, cw.make_reminder_message(
                    task["title"], task["due_date"], 0, task["id"]))
                db.update_task(task["id"], {"reminded_today": 1})
        except Exception as e:
            print(f"[remind] task {task['id']} error: {e}")

# ─── 定期タスク生成 ───────────────────────────────────────────

async def generate_recurring():
    today = date.today()
    if today.day != 1:
        return
    recurring = db.get_recurring()
    for rec in recurring:
        if not rec["active"]:
            continue
        last = rec.get("last_generated")
        if last and date.fromisoformat(last).month == today.month:
            continue
        task_id = db.create_task({
            "title": rec["title"],
            "body": rec.get("template", ""),
            "summary": rec["title"][:30],
            "assignee": rec.get("assignee"),
            "chatwork_room_id": rec.get("chatwork_room_id"),
        })
        if cw_client and rec.get("chatwork_room_id"):
            try:
                await cw_client.send_message(
                    rec["chatwork_room_id"],
                    f"[info][title]📅 定期タスク生成[/title]{rec['title']}[/info]"
                )
            except Exception:
                pass
        db.update_recurring(rec["id"], {"last_generated": today.isoformat()})

# ─── スケジューラ ─────────────────────────────────────────────

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    scheduler.add_job(poll_chatwork,      "interval", minutes=10, id="poll")
    scheduler.add_job(send_reminders,     "cron",     hour=9, minute=0, id="remind")
    scheduler.add_job(generate_recurring, "cron",     hour=9, minute=30, id="recurring")
    scheduler.start()
    yield
    scheduler.shutdown()

# ─── FastAPI ──────────────────────────────────────────────────

app = FastAPI(title="CS_HUBくん", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")

# ─── Pydantic models ──────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str
    body: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = "open"
    priority: Optional[str] = "normal"
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    chatwork_room_id: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assignee: Optional[str] = None
    due_date: Optional[str] = None

class BulkUpdate(BaseModel):
    task_ids: List[int]
    assignee: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    status: Optional[str] = None

class ReplyCreate(BaseModel):
    body: str

class RecurringCreate(BaseModel):
    title: str
    template: Optional[str] = None
    assignee: Optional[str] = None
    day_of_month: Optional[int] = 1
    chatwork_room_id: Optional[str] = None

class RecurringUpdate(BaseModel):
    title: Optional[str] = None
    template: Optional[str] = None
    assignee: Optional[str] = None
    day_of_month: Optional[int] = None
    chatwork_room_id: Optional[str] = None
    active: Optional[int] = None

# ─── Tasks API ────────────────────────────────────────────────

@app.get("/api/tasks")
def list_tasks(
    assignee: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
):
    return db.get_tasks(assignee=assignee, status=status, priority=priority, search=search)

@app.post("/api/tasks", status_code=201)
async def create_task(body: TaskCreate):
    data = body.dict(exclude_none=False)
    if not data.get("summary"):
        data["summary"] = await generate_summary(data.get("body") or data["title"])
    task_id = db.create_task(data)
    return {"id": task_id}

@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404)
    return t

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404)
    data = {k: v for k, v in body.dict().items() if v is not None}
    if data.get("status") in ("done", "closed") and t["status"] not in ("done", "closed"):
        data["completed_at"] = datetime.now().isoformat()
    db.update_task(task_id, data)
    return db.get_task(task_id)

@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: int):
    db.delete_task(task_id)

@app.post("/api/tasks/bulk")
def bulk_update(body: BulkUpdate):
    db.bulk_update_tasks(body.task_ids, body.dict(exclude={"task_ids"}, exclude_none=True))
    return {"updated": len(body.task_ids)}

# ─── Threads API ──────────────────────────────────────────────

@app.get("/api/tasks/{task_id}/threads")
def get_threads(task_id: int):
    return db.get_threads(task_id)

@app.post("/api/tasks/{task_id}/reply", status_code=201)
async def reply(task_id: int, body: ReplyCreate):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(404)
    msg_id = None
    if cw_client and t.get("chatwork_room_id"):
        try:
            res = await cw_client.send_message(t["chatwork_room_id"], body.body)
            msg_id = str(res.get("message_id", ""))
        except Exception as e:
            print(f"[reply] send error: {e}")
    thread_id = db.add_thread(task_id, {
        "chatwork_message_id": msg_id,
        "sender_name": "CS_HUBくん",
        "body": body.body,
        "direction": "outbound",
    })
    db.update_task(task_id, {})
    return {"id": thread_id}

# ─── Dashboard API ────────────────────────────────────────────

@app.get("/api/dashboard")
def dashboard():
    return db.get_dashboard_stats()

# ─── Chatwork手動操作 ─────────────────────────────────────────

@app.post("/api/chatwork/poll")
async def manual_poll():
    await poll_chatwork()
    return {"status": "ok"}

@app.get("/api/chatwork/rooms")
async def get_cw_rooms():
    if not cw_client:
        return []
    return await cw_client.get_rooms()

@app.get("/api/settings")
def get_settings():
    result = {}
    for name in ["金子", "和田", "福江"]:
        result[name] = {
            "account_id": db.get_setting(f"staff_account_{name}"),
            "room_id":    db.get_setting(f"staff_room_{name}") or STAFF_ROOMS.get(name, ""),
        }
    return {"staff": result}

@app.put("/api/settings")
async def update_settings(body: dict):
    resolved = {}
    for name, account_id in body.get("staff_accounts", {}).items():
        account_id = (account_id or "").strip()
        db.set_setting(f"staff_account_{name}", account_id)
        room_id = await resolve_dm_room(account_id)
        db.set_setting(f"staff_room_{name}", room_id)
        resolved[name] = {"account_id": account_id, "room_id": room_id}
    return {"resolved": resolved}

@app.get("/api/chatwork/detected-rooms")
async def detected_rooms():
    if not cw_client:
        return []
    try:
        rooms = await cw_client.get_rooms()
        return [{"room_id": str(r["room_id"]), "name": r.get("name", str(r["room_id"])), "type": r.get("type", "")}
                for r in rooms if r.get("type") in ("group", "direct")]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/config")
def get_config():
    return {
        "room_ids": ROOM_IDS,
        "hub_account_id": HUB_ACCOUNT_ID,
        "ai_enabled": AI_ENABLED,
        "staff_rooms": STAFF_ROOMS,
    }

# ─── Recurring API ────────────────────────────────────────────

@app.get("/api/recurring")
def list_recurring():
    return db.get_recurring()

@app.post("/api/recurring", status_code=201)
def create_recurring(body: RecurringCreate):
    rid = db.create_recurring(body.dict())
    return {"id": rid}

@app.put("/api/recurring/{rec_id}")
def update_recurring(rec_id: int, body: RecurringUpdate):
    db.update_recurring(rec_id, {k: v for k, v in body.dict().items() if v is not None})
    return {"status": "ok"}

@app.delete("/api/recurring/{rec_id}", status_code=204)
def delete_recurring(rec_id: int):
    db.delete_recurring(rec_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8082, reload=True)
