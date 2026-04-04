# MCヤスくん（CS_HUBくん） Claude用仕様書

> このファイルをClaudeにそのままコピペして相談してください。
> 「このシステムで〇〇したい」「エラーが出た」など何でもOKです。

---

## システム概要

ChatworkのメッセージをAIで自動タスク化し、ダッシュボードで管理するWebツール。

**ユースケース:**
- 誰かがChatworkでメンションを送る
- MCヤスくん（ボット）が10分以内に検知
- 管理ダッシュボードにタスクが自動生成される
- 担当者をアサイン → 進捗管理 → 完了通知

---

## 技術スタック

| 層 | 技術 |
|----|------|
| バックエンド | Python / FastAPI |
| DB | SQLite（`/data/cs_hub.db`）|
| フロントエンド | バニラHTML/JS（`static/index.html`）|
| デプロイ | Fly.io（SQLite Volume永続化）|
| Chatwork連携 | Chatwork API v2 |

---

## ファイル構成

```
cs_hub/
├── main.py          # APIルーティング・スケジューラー（10分ポーリング）
├── db.py            # SQLite CRUD・テーブル定義
├── chatwork.py      # ChatworkAPIクライアント・メッセージパース
├── requirements.txt # 依存パッケージ
├── Dockerfile       # Fly.ioデプロイ用
├── fly.toml         # Fly.io設定（app名・リージョン・Volume設定）
├── static/
│   └── index.html   # ダッシュボードUI（SPA）
└── docs/
    ├── SPEC.md               # 詳細仕様書
    ├── HANDOVER_YASU_FLYIO.md # セットアップガイド
    └── CLAUDE_SPEC.md        # このファイル
```

---

## 環境変数（Fly.io secrets）

| 変数名 | 説明 | 例 |
|--------|------|----|
| `CHATWORK_API_TOKEN` | Chatwork APIトークン | `abc123...` |
| `CHATWORK_HUB_ACCOUNT_ID` | ボットのアカウントID | `12345678` |
| `CHATWORK_ROOM_IDS` | 監視ルームID（カンマ区切り）| `111222,333444` |
| `STAFF_NAMES` | スタッフ名（カンマ区切り）| `ヤス,田中` |
| `DB_PATH` | DBファイルパス | `/data/cs_hub.db` |
| `AI_SUMMARY_ENABLED` | AI要約ON/OFF | `false` |
| `ANTHROPIC_API_KEY` | Claude APIキー（AI時のみ）| `sk-ant-...` |

---

## 主なAPIエンドポイント

```
GET  /api/tasks               タスク一覧
POST /api/tasks               タスク作成
PUT  /api/tasks/{id}          タスク更新（ステータス・担当者・期限）
DELETE /api/tasks/{id}        タスク削除
POST /api/tasks/bulk          一括更新

GET  /api/tasks/{id}/threads  スレッド（会話履歴）
POST /api/tasks/{id}/reply    Chatworkへ返信

GET  /api/dashboard           KPI・アラート統計
POST /api/chatwork/poll       手動ポーリング（即時反映したいとき）

GET  /api/settings            設定一覧
PUT  /api/settings            設定更新
GET  /api/recurring           定期タスク一覧
POST /api/recurring           定期タスク作成
```

---

## データベーステーブル（主要）

### tasks（タスク本体）
```sql
id, title, body, summary, status, priority, assignee,
due_date, chatwork_room_id, chatwork_room_name,
chatwork_message_id, sender_name, sender_account_id,
created_at, updated_at, completed_at, unread_reply
```

**status値:** `open` / `in_progress` / `done` / `closed`
**priority値:** `urgent` / `high` / `normal` / `low`

### task_threads（会話履歴）
```sql
id, task_id, chatwork_message_id, sender_name,
body, direction(inbound/outbound), sent_at
```

### recurring_tasks（定期タスク）
```sql
id, title, template, assignee, day_of_month, active
```

---

## Chatwork連携の仕組み

### タスク生成トリガー
```
[To:ボットのアカウントID] MCヤスくん
対応お願いします。
```
→「対応お願いします。」がタスクになる

### ポーリング間隔
10分ごとに自動実行。すぐ反映したい場合は `/api/chatwork/poll` を叩く。

### 返信の紐付けロジック
1. 引用付き返信 (`[rp aid=X to=ROOM-MSG_ID]`) → 引用元タスクのスレッドに追加
2. 引用なし → 同ルーム内の最後に更新されたopenタスクに追加

---

## Fly.io 運用コマンド

```bash
# デプロイ
fly deploy

# ログ確認
fly logs

# 環境変数の追加・変更
fly secrets set 変数名=値

# 環境変数の一覧
fly secrets list

# アプリの状態確認
fly status

# SSH接続（DB直接確認など）
fly ssh console
```

---

## よくある作業とヒント

**スタッフを追加したい**
→ `STAFF_NAMES` に追加 → `fly secrets set STAFF_NAMES=ヤス,田中,新しい人`

**監視ルームを追加したい**
→ `CHATWORK_ROOM_IDS` に追加 → `fly secrets set CHATWORK_ROOM_IDS=既存ID,新しいID`

**タスクが生成されない**
→ `fly logs` でエラーを確認 → ChatworkルームにMCヤスくんが招待されているか確認

**DBを直接見たい**
```bash
fly ssh console
sqlite3 /data/cs_hub.db
.tables
SELECT * FROM tasks ORDER BY created_at DESC LIMIT 10;
```

**UIを変更したい**
→ `static/index.html` を編集 → `fly deploy`

**新機能を追加したい**
→ `main.py`（API）と `static/index.html`（UI）を編集 → `fly deploy`

---

## GitHub リポジトリ

元のコード: https://github.com/tfunakita/cs_hub

```bash
# 最新コードを取得
git pull origin main

# 変更をデプロイ
git add . && git commit -m "変更内容" && git push origin main
fly deploy
```
