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
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程服务器，支持并发请求。"""
    daemon_threads = True

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
INBOX_FILE = os.path.join(os.path.dirname(__file__), "inbox.md")
REPLIES_FILE = os.path.join(os.path.dirname(__file__), "replies.json")

REPLY_SYSTEM_PROMPT = """你是一位严肃的哲学对话者。你来这里不是为了安慰或鼓励，而是为了帮助你和对谈者一起把问题想得更清楚。

你的准则：
1. 准确理解对方——先用自己的话复述对方的观点，确认你真的理解了。如果对方的表述有歧义，指出歧义并问清楚。
2. 不讨好，不拍马屁。如果对方的论证有漏洞，直接指出。如果对方的观点你不同意，说出你的理由。你对对方的尊重体现在认真对待ta的想法，而不是附合ta。
3. 每一个观点都需要支撑。不要说"这让我想到XX"然后就滑过去——解释为什么XX与此相关，它的逻辑脉络是什么。
4. 公平原则同样适用于你。如果你的某个判断缺乏依据，承认这一点。如果你不确定，就说你不确定。
5. 对方也可以要求你证明你的观点。当对方质疑你时，不要防御——用论证回应。

风格：
- 语言简洁、精确。少用形容词，多用具体的论证步骤。
- 不煽情，不制造"被击中了"的感觉。如果对方被触动，那应该是因为想法的力量，而不是你的修辞。
- 回复 150-300 字。不要浪费字数在寒暄上。

你的姿态像一位好的学术讨论者：认真、诚实、对自己和对方都有智识上的要求。"""

SYSTEM_PROMPT = """你是一位哲学导师，擅长提出引人深思的问题。

请生成一个哲学思辨问题，要求：
1. 用中文表达，语言优美，像一首短诗或箴言
2. 触及存在、意识、时间、自由、爱、死亡、美、语言、真实、自我等哲学母题
3. 问题本身要让人停下来，感到一种"被击中"的感觉
4. 不要陈词滥调，不要教科书式的问题
5. 同时返回一个简短的"来源标注"（3-8个字），标明这个问题与哪个哲学传统或思想家有关联，格式如"—— 海德格尔与存在"或"—— 庄子与逍遥"

请直接返回 JSON 格式：
{"q": "问题文本", "src": "—— 来源标注"}"""


def _deepseek(messages, max_tokens=600, model="deepseek-chat"):
    """Call DeepSeek API (OpenAI-compatible)."""
    if not DEEPSEEK_KEY:
        raise ValueError("未设置 DEEPSEEK_API_KEY")
    body = json.dumps({
        "model": model,
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
        history = body.get("history", None)
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
        reply = self.generate_reply(text, prompt, history)
        if reply:
            self.send_json({"ok": True, "chars": len(text), "reply": reply})
        else:
            self.send_json({"ok": True, "chars": len(text), "reply_fallback": True})

    def generate_reply(self, text, prompt, history=None):
        """Use DeepSeek API to generate a philosophical reply."""
        if not DEEPSEEK_KEY:
            print("  ⚠ 未设置 DEEPSEEK_API_KEY，跳过 AI 回复")
            return None

        # 构建消息数组：system + 历史 + 当前用户消息
        messages = [{"role": "system", "content": REPLY_SYSTEM_PROMPT}]

        if history:
            for msg in history:
                role = "assistant" if msg.get("role") == "claude" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})

        user_content = "用户写下了以下思辨文字：\n\n"
        if prompt:
            user_content += f"（用户在回应这个问题：「{prompt}」）\n\n"
        user_content += text
        messages.append({"role": "user", "content": user_content})

        try:
            print("  → 正在用 DeepSeek R1 生成 AI 回复…")
            reply = _deepseek(messages, max_tokens=600, model="deepseek-reasoner")
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

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已关闭")
        server.server_close()
