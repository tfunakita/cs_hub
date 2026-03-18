# CS_HUBくん — Claude Code 指示書

## このシステムは何？

ChatworkのメッセージをAIで自動タスク化し、CSチームの業務を一元管理するWebツール。
本番は Railway でサーバー稼働中。

```
Chatwork（メンション付きメッセージ）
   ↓ 10分ごとにポーリング
CS_HUBくん
   ├── タスク自動生成
   ├── AI要約
   ├── 担当者アサイン
   ├── 期限リマインド送信
   └── Webダッシュボード
```

## リンク

- **本番URL**: https://cshub-production-3331.up.railway.app/
- **GitHub**: https://github.com/tfunakita/cs_hub
- **仕様書**: `docs/SPEC.md`（全機能の詳細はここ）

## ファイル構成

```
cs_hub/
├── main.py        # FastAPIアプリ本体・ルーティング・スケジューラー
├── db.py          # SQLite操作（CRUD）・スキーマ定義
├── chatwork.py    # Chatwork APIクライアント・メッセージパース
├── requirements.txt
├── railway.toml   # Railwayデプロイ設定
├── static/
│   └── index.html # フロントエンド（SPA・バニラJS）
└── docs/
    └── SPEC.md    # 完全仕様書
```

## ローカル起動

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8082
```

ブラウザで http://localhost:8082 を開く。

## 環境変数（.env ファイルを作成）

```
CHATWORK_API_TOKEN=（別途受け取ってください）
CHATWORK_HUB_ACCOUNT_ID=（CS_HUBくんのアカウントID）
CHATWORK_ROOM_IDS=（監視ルームID、カンマ区切り）
STAFF_NAMES=（スタッフ名、カンマ区切り）
DB_PATH=./cs_hub.db
```

## 本番への反映方法

```bash
git add .
git commit -m "変更内容を書く"
git push origin main
```

**pushしたら Railway が自動でデプロイする。**（約1〜2分で反映）

## よくある修正依頼の例

Claude Code にそのまま伝えればOK：

- 「タスク一覧の表示順を期限が近い順にして」
- 「ダッシュボードに未対応タスク数を大きく表示して」
- 「リマインドを期限3日前にも送るようにして」
- 「スタッフ名に〇〇を追加して」
- 「定期タスクの文面を変更して」

## 注意事項

- DB（`cs_hub.db`）は Railway の Persistent Volume に保存。ローカルのDBとは別物
- 環境変数は Railway の Variables に設定済み。ローカルは `.env` ファイルで管理
- `main.py` を変更したら必ず動作確認してから push すること
