import httpx
import re
from typing import Optional

BASE = "https://api.chatwork.com/v2"

class ChatworkClient:
    def __init__(self, api_token: str):
        self.headers = {"X-ChatWorkToken": api_token}

    async def _get(self, path: str, params: dict = None):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{BASE}{path}", headers=self.headers, params=params or {})
            r.raise_for_status()
            return r.json()

    async def _post(self, path: str, data: dict = None):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{BASE}{path}", headers=self.headers, data=data or {})
            r.raise_for_status()
            return r.json()

    async def get_me(self) -> dict:
        return await self._get("/me")

    async def get_rooms(self) -> list:
        return await self._get("/rooms")

    async def get_messages(self, room_id: str, force: int = 1) -> list:
        try:
            return await self._get(f"/rooms/{room_id}/messages", {"force": force})
        except Exception:
            return []

    async def send_message(self, room_id: str, body: str) -> dict:
        return await self._post(f"/rooms/{room_id}/messages", {"body": body, "self_unread": 0})

    async def get_room_members(self, room_id: str) -> list:
        return await self._get(f"/rooms/{room_id}/members")


def parse_mentions(body: str, hub_account_id: str) -> bool:
    """メッセージにCS_HUBくんへのメンションが含まれるか判定"""
    return f"[To:{hub_account_id}]" in body

def parse_reply_reference(body: str) -> str | None:
    """[rp aid=X to=ROOM-MESSAGE_ID] から参照先メッセージIDを取得"""
    m = re.search(r'\[rp\s+aid=\d+\s+to=\d+-(\d+)\]', body)
    return m.group(1) if m else None


def clean_body(body: str) -> str:
    """Chatworkの記法を除去してプレーンテキスト化"""
    body = re.sub(r"\[To:\d+\][^\n]*", "", body)  # [To:12345]名前 を行ごと除去
    body = re.sub(r"\[info\]|\[\/info\]|\[title\]|\[\/title\]", "", body)
    body = re.sub(r"\[code\]|\[\/code\]", "", body)
    return body.strip()


def make_mention(account_id: str, name: str) -> str:
    return f"[To:{account_id}] {name}さん\n"


def make_task_ack(task_id: int, title: str) -> str:
    return f"[info][title]✅ タスク受付完了 #{task_id}[/title]{title}\nCS管理ツールで担当者をアサインします。[/info]"


def make_reminder_message(task_title: str, due_date: str, days: int, task_id: int) -> str:
    if days == 0:
        label = "【本日期限】"
    elif days == 1:
        label = "【明日期限】"
    else:
        label = f"【{days}日後期限】"
    return f"[info][title]⏰ リマインド {label}[/title]タスク: {task_title}\n期限: {due_date}\n\nCS管理ツール: http://localhost:8082[/info]"
