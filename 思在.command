#!/bin/bash
cd "$(dirname "$0")"

# Kill any old server on this port
lsof -ti:8899 2>/dev/null | xargs kill -9 2>/dev/null

# Start server
python3 server.py &
SERVER_PID=$!
sleep 1

# Open browser
open http://localhost:8899

echo ""
echo "  思·在 已启动"
echo "  浏览器: http://localhost:8899"
echo "  停止: 关闭这个窗口 或 kill $SERVER_PID"
echo ""

# Keep the terminal window open while server runs
wait $SERVER_PID 2>/dev/null
