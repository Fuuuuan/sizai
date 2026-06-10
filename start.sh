#!/bin/bash
# 思·在 — 启动脚本
# 同时启动 AI 生成服务器和打开浏览器

cd "$(dirname "$0")"

echo "🚀 启动 思·在…"
echo ""

# Start the Python server in the background
python3 server.py &
SERVER_PID=$!

# Wait for server to be ready
sleep 1

# Open in browser
open http://localhost:8899

echo ""
echo "📡 AI 服务器运行中 (PID: $SERVER_PID)"
echo "🌐 浏览器已打开 http://localhost:8899"
echo ""
echo "按 Ctrl+C 停止服务器"

# Wait for server to finish
wait $SERVER_PID
