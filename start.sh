#!/bin/bash
cd "$(dirname "$0")"

# サーバー起動
venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8082 &
SERVER_PID=$!

sleep 2

# ngrok トンネル起動（バックグラウンド）
./ngrok http 8082 --log=stdout --log-level=info &
NGROK_PID=$!

sleep 3

# 公開URLを取得して表示
URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" 2>/dev/null)
echo ""
echo "======================================="
echo "  CS_HUBくん 起動完了"
echo "  ローカル : http://localhost:8082"
echo "  外部URL  : $URL"
echo "======================================="
echo ""

# 両プロセスを待機
wait $SERVER_PID $NGROK_PID
