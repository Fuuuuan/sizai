#!/usr/bin/env python3
"""思·在 — 哲学问题生成服务器
使用 Anthropic API 实时生成全新的哲学问题。
需要设置环境变量 ANTHROPIC_API_KEY。
如果没有 API key，前端会自动使用内嵌题库。
"""

import json
import os
import urllib.request
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
INBOX_FILE = os.path.join(os.path.dirname(__file__), "inbox.md")
REPLIES_FILE = os.path.join(os.path.dirname(__file__), "replies.json")

REPLY_SYSTEM_PROMPT = """你是一位哲学对话伙伴，用户在「思·在」思辨花园里写下了他们的思考。
你的任务是用中文给用户一个真诚、有深度的回复。

规则：
1. 像一个在深夜咖啡馆里和你聊天的朋友，不是一个导师或老师
2. 先承接用户的话——表示你真的读了、想了
3. 然后追问或拓展——把思辨往前推一步
4. 可以引用相关的哲学思想，但不要掉书袋
5. 保持温暖、好奇的语气，不要评判
6. 回复控制在 150-300 字之间
7. 偶尔可以反问用户，把话题抛回去"""

SYSTEM_PROMPT = """你是一位哲学导师，擅长提出引人深思的问题。

请生成一个哲学思辨问题，要求：
1. 用中文表达，语言优美，像一首短诗或箴言
2. 触及存在、意识、时间、自由、爱、死亡、美、语言、真实、自我等哲学母题
3. 问题本身要让人停下来，感到一种"被击中"的感觉
4. 不要陈词滥调，不要教科书式的问题
5. 同时返回一个简短的"来源标注"（3-8个字），标明这个问题与哪个哲学传统或思想家有关联，格式如"—— 海德格尔与存在"或"—— 庄子与逍遥"

请直接返回 JSON 格式：
{"q": "问题文本", "src": "—— 来源标注"}"""


def generate_question():
    """调用 Anthropic API 生成一个全新的哲学问题。"""
    if not API_KEY:
        raise ValueError("未设置 ANTHROPIC_API_KEY")

    body = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 200,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "请生成一个全新的哲学问题。"}],
    }).encode("utf-8")

    req = urllib.request.Request(API_URL, data=body, headers={
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })

    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    text = data["content"][0]["text"]
    # Parse the JSON from the response
    # Handle possible markdown code block wrapping
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def do_GET(self):
        if self.path == "/api/question":
            self.handle_question()
        elif self.path == "/api/inbox":
            self.handle_get_inbox()
        elif self.path == "/api/ping":
            self.send_json({"ok": True, "has_api_key": bool(API_KEY)})
        elif self.path == "/api/replies":
            self.handle_get_replies()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/submit":
            self.handle_submit()
        else:
            self.send_json({"error": "not_found"}, 404)

    def handle_question(self):
        if not API_KEY:
            self.send_json({"error": "no_api_key"})
            return

        try:
            question = generate_question()
            self.send_json(question)
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_submit(self):
        """Receive a writing from the user, save to inbox, and generate AI reply."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "invalid_json"}, 400)
            return

        text = body.get("text", "").strip()
        prompt = body.get("prompt", "")
        if not text:
            self.send_json({"error": "empty_text"}, 400)
            return

        # Append to inbox markdown file
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n---\n**{timestamp}**\n\n"
        if prompt:
            entry += f"> 回应：「{prompt}」\n\n"
        entry += f"{text}\n"

        with open(INBOX_FILE, "a", encoding="utf-8") as f:
            f.write(entry)

        print(f"  ✦ 收到思辨文字 ({len(text)} 字)")

        # Generate AI reply via Claude CLI
        reply = self.generate_reply(text, prompt)
        if reply:
            self.send_json({"ok": True, "chars": len(text), "reply": reply})
        else:
            self.send_json({"ok": True, "chars": len(text), "reply_fallback": True})

    def generate_reply(self, text, prompt):
        """Use Anthropic API directly to generate a philosophical reply."""
        if not API_KEY:
            print("  ⚠ 未设置 API key，跳过 AI 回复")
            return None

        user_content = "用户写下了以下思辨文字：\n\n"
        if prompt:
            user_content += f"（用户在回应这个问题：「{prompt}」）\n\n"
        user_content += text

        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 600,
            "system": REPLY_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_content}],
        }).encode("utf-8")

        try:
            print("  → 正在生成 AI 回复…")
            req = urllib.request.Request(API_URL, data=body, headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            reply = data["content"][0]["text"].strip()
            if reply:
                self.save_reply(text[:30], reply)
                print(f"  ✓ AI 回复已生成 ({len(reply)} 字)")
                return reply
            else:
                print("  ⚠ AI 回复为空")
                return None
        except Exception as e:
            print(f"  ⚠ AI 回复失败: {e}")
            return None

    def save_reply(self, reply_to_preview, reply_text):
        """Append a reply to the replies file."""
        replies = []
        if os.path.exists(REPLIES_FILE):
            with open(REPLIES_FILE, "r", encoding="utf-8") as f:
                replies = json.load(f)
        replies.append({
            "date": datetime.now().isoformat(),
            "reply_to": reply_to_preview,
            "text": reply_text,
        })
        with open(REPLIES_FILE, "w", encoding="utf-8") as f:
            json.dump(replies, f, ensure_ascii=False, indent=2)

    def handle_get_inbox(self):
        """Return the inbox content (for the dialogue panel)."""
        if not os.path.exists(INBOX_FILE):
            self.send_json({"entries": []})
            return
        with open(INBOX_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        # Parse entries separated by ---
        parts = content.split("\n---\n")
        entries = [p.strip() for p in parts if p.strip()]
        self.send_json({"entries": entries, "count": len(entries)})

    def handle_get_replies(self):
        """Return all Claude replies."""
        if not os.path.exists(REPLIES_FILE):
            self.send_json([])
            return
        with open(REPLIES_FILE, "r", encoding="utf-8") as f:
            replies = json.load(f)
        self.send_json(replies)

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # Quieter logging
        if "/api/" in str(args[0]):
            print(f"  → API 请求: {args[0]}")
        else:
            pass  # suppress static file logs


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8899"))
    print("=" * 50)
    print("  思·在 — 哲学问题生成服务器")
    print("=" * 50)
    if API_KEY:
        print(f"  ✓ API key 已加载 ({API_KEY[:8]}...)")
        print(f"  ✓ AI 实时生成模式")
    else:
        print("  ⚠ 未设置 ANTHROPIC_API_KEY")
        print("  ⚠ AI 生成不可用，前端将使用内嵌题库")
        print("  → 获取 key: https://console.anthropic.com/")
        print("  → 设置: export ANTHROPIC_API_KEY='your-key'")
    print(f"  → 服务器启动在: http://{host}:{port}")
    print("=" * 50)

    server = HTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已关闭")
        server.server_close()
