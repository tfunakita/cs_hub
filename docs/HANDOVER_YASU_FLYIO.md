# MCヤスくん セットアップガイド（Fly.io版）

> 無料でサーバーを立てられる Fly.io を使います。
> コマンドは全部コピペでOKです。Claude に相談しながら進めてください。

---

## 事前に準備するもの（Chatwork情報）

以下を手元にメモしておいてください：

| 必要な情報 | 取得方法 |
|-----------|---------|
| Chatwork APIトークン | Chatworkログイン → 右上プロフィール → サービス連携 → APIトークン発行 |
| MCヤスくんのアカウントID | MCヤスくん専用アカウントでログイン → プロフィールURL内の数字 |
| 監視するルームID | 監視したいグループルームを開く → URLの `rid=` 以降の数字 |
| スタッフ名リスト | 例: `ヤス,田中,鈴木`（カンマ区切り）|

> **MCヤスくん専用アカウントを1つ新規作成してください**（このアカウントがボットとして動きます）

---

## セットアップ手順

### STEP 1: アカウント作成

1. [GitHub](https://github.com) アカウントを作成（なければ）
2. [Fly.io](https://fly.io) にGitHubアカウントでサインアップ
3. クレジットカード登録が必要ですが、**無料枠内なら課金されません**

### STEP 2: コードをGitHubにコピーする

1. [https://github.com/tfunakita/cs_hub](https://github.com/tfunakita/cs_hub) を開く
2. 右上の「**Fork**」ボタンを押す
3. 「Create fork」を押す → 自分のGitHubにコピーされる

### STEP 3: ターミナルを開く

Macなら: Spotlight（Cmd+Space）→「ターミナル」と入力して開く

### STEP 4: Fly.io CLIをインストールする

以下をターミナルにコピペして Enter：

```bash
brew install flyctl
```

終わったら：

```bash
fly auth login
```

ブラウザが開くのでFly.ioにログイン。

### STEP 5: コードをダウンロードする

以下を1行ずつコピペ（`あなたのGitHubユーザー名` の部分は自分のものに変える）：

```bash
git clone https://github.com/あなたのGitHubユーザー名/cs_hub.git
cd cs_hub
```

### STEP 6: Fly.ioにデプロイする

```bash
fly launch --name mc-yasu-hub --region nrt --no-deploy
```

途中で「Would you like to copy its configuration to the new app?」と聞かれたら `y` を入力。

### STEP 7: データ保存領域を作る

```bash
fly volumes create data --region nrt --size 1
```

### STEP 8: 環境変数を設定する

以下を1つずつコピペ（`xxxxx` 部分を実際の値に変えてから実行）：

```bash
fly secrets set CHATWORK_API_TOKEN=ここにAPIトークン
fly secrets set CHATWORK_HUB_ACCOUNT_ID=ここにアカウントID
fly secrets set CHATWORK_ROOM_IDS=ここにルームID
fly secrets set STAFF_NAMES=ヤス,田中,鈴木
fly secrets set DB_PATH=/data/cs_hub.db
fly secrets set AI_SUMMARY_ENABLED=false
```

### STEP 9: デプロイする

```bash
fly deploy
```

しばらく待つ（2〜3分）。「Visit your newly deployed app at: https://mc-yasu-hub.fly.dev」と表示されれば完了。

### STEP 10: 動作確認

1. 表示されたURLをブラウザで開く
2. ダッシュボードが表示されればOK
3. 監視ルームにMCヤスくんアカウントを招待
4. メンションを送ってみる：
   ```
   [To:MCヤスくんのアカウントID] MCヤスくん
   テスト送信です。
   ```
5. 10分以内にダッシュボードにタスクが現れれば完了

---

## 使い方

### タスクを作る

MCヤスくんにメンションするだけ：
```
[To:アカウントID] MCヤスくん
〇〇の件、確認お願いします。
```
→ 10分以内に自動でタスクになります。

### ダッシュボードの画面

| タブ | 内容 |
|-----|------|
| ダッシュボード | KPI・未対応アラート・担当者別状況 |
| 振り分け | 担当者が未定のタスク一覧 |
| タスク一覧 | 全タスク・検索・絞り込み |
| カンバン | ステータス別カード表示 |
| 設定 | スタッフ追加・定期タスク設定 |

### ステータスの意味

| ステータス | 意味 |
|-----------|------|
| open | 未着手 |
| in_progress | 対応中 |
| done | 完了 |
| closed | クローズ |

---

## 困ったときは

**Claude（AI）に相談する場合、このファイルと一緒に `CLAUDE_SPEC.md` をコピペして相談してください。**

---

## よくある質問

**Q. タスクが自動生成されない**
- MCヤスくんを監視ルームに招待しているか確認
- 10分待ってから再確認

**Q. URLにアクセスできない**
- `fly status` をターミナルで実行してエラーがないか確認

**Q. 環境変数を変更したい**
```bash
fly secrets set 変数名=新しい値
```

**Q. ログを見たい**
```bash
fly logs
```
