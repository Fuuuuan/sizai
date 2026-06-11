#!/usr/bin/env python3
"""思·在 — 哲学问题生成服务器
使用 DeepSeek API，兼容 OpenAI 格式。
需要设置环境变量 DEEPSEEK_API_KEY。
"""

import json
import os
import urllib.request
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
INBOX_FILE = os.path.join(os.path.dirname(__file__), "inbox.md")
REPLIES_FILE = os.path.join(os.path.dirname(__file__), "replies.json")

REPLY_SYSTEM_PROMPT = """你是一位哲学对话伙伴。此刻你们坐在深夜的咖啡馆里，窗外是沉默的夜色，而你们正在认真谈论那些真正重要的事。

你的风格：
- 真诚——你真的读了对方的话，先承接，再回应
- 有深度——把思辨往前推一步，而不是停在表面
- 敢于追问——不回避尖锐的角度，不满足于安全的共识。如果对方的想法有裂缝，就走进去看看里面藏着什么
- 像一个骑士面对黑暗那样——不是鲁莽，而是带着勇气直视那些让人不安的问题。不粉饰，不逃避，但也不因此变得冷酷
- 同时你是可靠的、温暖的——你不是一个辩论对手，而是一个值得信任的人，在此刻陪伴对方一起思考

规则：
1. 像深夜咖啡馆里的朋友聊天，不是导师授课
2. 先承接用户的话，再追问或拓展
3. 可以引用哲学思想，但用你自己的话说，不要掉书袋
4. 敢于质疑、敢于提供不同的视角，但语气保持尊重
5. 回复控制在 150-300 字
6. 偶尔把话题抛回去——反问用户，邀请ta继续"""

SYSTEM_PROMPT = """你是一位哲学导师，擅长提出引人深思的问题。

请生成一个哲学思辨问题，要求：
1. 用中文表达，语言优美，像一首短诗或箴言
2. 触及存在、意识、时间、自由、爱、死亡、美、语言、真实、自我等哲学母题
3. 问题本身要让人停下来，感到一种"被击中"的感觉
4. 不要陈词滥调，不要教科书式的问题
5. 同时返回一个简短的"来源标注"（3-8个字），标明这个问题与哪个哲学传统或思想家有关联，格式如"—— 海德格尔与存在"或"—— 庄子与逍遥"

请直接返回 JSON 格式：
{"q": "问题文本", "src": "—— 来源标注"}"""


def _deepseek(messages, max_tokens=600):
    """Call DeepSeek API (OpenAI-compatible)."""
    if not DEEPSEEK_KEY:
        raise ValueError("未设置 DEEPSEEK_API_KEY")
    body = json.dumps({
        "model": "deepseek-chat",
        "max_tokens": max_tokens,
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(DEEPSEEK_URL, data=body, headers={
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def generate_question():
    """调用 DeepSeek API 生成一个全新的哲学问题。"""
    text = _deepseek([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "请生成一个全新的哲学问题。"},
    ], max_tokens=200)
    # Parse the JSON from the response (handle possible markdown wrapping)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
    return json.loads(text)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(__file__), **kwargs)

    def _check_auth(self):
        """如果设置了 ACCESS_CODE，检查请求头中的授权码。"""
        if not ACCESS_CODE:
            return True
        auth = self.headers.get("X-Sizai-Auth", "")
        return auth == ACCESS_CODE

    def do_GET(self):
        if self.path == "/api/question":
            self.handle_question()
        elif self.path == "/api/inbox":
            self.handle_get_inbox()
        elif self.path == "/api/ping":
            self.send_json({
                "ok": True,
                "has_api_key": bool(DEEPSEEK_KEY),
                "needs_auth": bool(ACCESS_CODE),
            })
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
        if not self._check_auth():
            self.send_json({"error": "unauthorized"}, 401)
            return
        if not DEEPSEEK_KEY:
            self.send_json({"error": "no_api_key"})
            return
        try:
            question = generate_question()
            self.send_json(question)
        except Exception as e:
            self.send_json({"error": str(e)})

    def handle_submit(self):
        """Receive a writing from the user, save to inbox, and generate AI reply."""
        if not self._check_auth():
            self.send_json({"error": "unauthorized"}, 401)
            return
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

        # Generate AI reply via DeepSeek
        reply = self.generate_reply(text, prompt)
        if reply:
            self.send_json({"ok": True, "chars": len(text), "reply": reply})
        else:
            self.send_json({"ok": True, "chars": len(text), "reply_fallback": True})

    def generate_reply(self, text, prompt):
        """Use DeepSeek API to generate a philosophical reply."""
        if not DEEPSEEK_KEY:
            print("  ⚠ 未设置 DEEPSEEK_API_KEY，跳过 AI 回复")
            return None

        user_content = "用户写下了以下思辨文字：\n\n"
        if prompt:
            user_content += f"（用户在回应这个问题：「{prompt}」）\n\n"
        user_content += text

        try:
            print("  → 正在用 DeepSeek 生成 AI 回复…")
            reply = _deepseek([
                {"role": "system", "content": REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ], max_tokens=600)
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
        parts = content.split("\n---\n")
        entries = [p.strip() for p in parts if p.strip()]
        self.send_json({"entries": entries, "count": len(entries)})

    def handle_get_replies(self):
        """Return all AI replies."""
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sizai-Auth")
        self.end_headers()

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            print(f"  → API 请求: {args[0]}")


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8899"))
    print("=" * 50)
    print("  思·在 — 哲学问题生成服务器 (DeepSeek)")
    print("=" * 50)
    if DEEPSEEK_KEY:
        print(f"  ✓ DeepSeek API key 已加载 ({DEEPSEEK_KEY[:8]}...)")
        print(f"  ✓ AI 实时生成模式")
    else:
        print("  ⚠ 未设置 DEEPSEEK_API_KEY")
        print("  ⚠ AI 生成不可用，前端将使用内嵌题库")
        print("  → 获取 key: https://platform.deepseek.com/api_keys")
        print("  → 设置: export DEEPSEEK_API_KEY='your-key'")
    print(f"  → 服务器启动在: http://{host}:{port}")
    print("=" * 50)

    server = HTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已关闭")
        server.server_close()
