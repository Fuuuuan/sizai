#!/usr/bin/env python3
"""思·在 — 哲学问题生成服务器
使用 DeepSeek API，兼容 OpenAI 格式。
需要设置环境变量 DEEPSEEK_API_KEY。
"""

import json
import os
import sqlite3
import hashlib
import secrets
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程服务器，支持并发请求。"""
    daemon_threads = True

DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
ACCESS_CODE = os.environ.get("ACCESS_CODE", "")
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "sizai.db")
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

SYSTEM_PROMPT = """你生成一个哲学命题，并标注它的思想来源。

命题要求：日常语言，清晰有力。触及自由、自我、意义、意识、时间、道德、真实、死亡、爱、知识等母题。不写诗，不用比喻。

来源标注：必须关联一个可查的哲学传统或思想家。格式"—— 思想家名与主题"，例：
- "—— 休谟与自我"  "—— 庄子与逍遥"  "—— 加缪与荒谬"
- "—— 康德与道德"  "—— 存在主义与选择"  "—— 佛教与无常"
来源标注是硬要求——每次必须包含。

范例：
{"q": "记忆每次被调取都在被改写。如果过去不可靠，你的自我建立在什么上面？", "src": "—— 休谟与自我"}
{"q": "自由意志可能不存在。但如果你相信它不存在，你的生活会发生什么变化？", "src": "—— 决定论与道德责任"}

返回JSON格式，q和src缺一不可。"""


def _deepseek(messages, max_tokens=600, model="deepseek-chat", temperature=None):
    """Call DeepSeek API (OpenAI-compatible)."""
    if not DEEPSEEK_KEY:
        raise ValueError("未设置 DEEPSEEK_API_KEY")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    body = json.dumps(payload).encode("utf-8")
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
        {"role": "user", "content": "生成一个哲学命题。日常语言，清晰有力。"},
    ], max_tokens=300, model="deepseek-reasoner")
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

    def _check_token(self):
        """验证用户 token，返回 user_id 或 None。"""
        token = self.headers.get("X-Sizai-Token", "")
        if not token:
            return None
        cur = db.cursor()
        cur.execute("SELECT user_id FROM sessions WHERE token=? AND expires>?", (token, datetime.now().isoformat()))
        row = cur.fetchone()
        return row[0] if row else None

    def do_GET(self):
        if self.path == "/api/question":
            self.handle_question()
        elif self.path == "/api/ping":
            self.send_json({
                "ok": True,
                "has_api_key": bool(DEEPSEEK_KEY),
                "needs_auth": bool(ACCESS_CODE),
            })
        elif self.path.startswith("/api/entries"):
            self.handle_get_entries()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/submit":
            self.handle_submit()
        elif self.path == "/api/summarize":
            self.handle_summarize()
        elif self.path == "/api/auth/signup":
            self.handle_signup()
        elif self.path == "/api/auth/login":
            self.handle_login()
        elif self.path == "/api/entries":
            self.handle_save_entry()
        elif self.path == "/api/entries/delete":
            self.handle_delete_entry()
        else:
            self.send_json({"error": "not_found"}, 404)

    # ── 认证端点 ──
    def handle_signup(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "invalid_json"}, 400)
            return
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")
        if not email or len(password) < 6:
            self.send_json({"error": "invalid_input"}, 400)
            return

        cur = db.cursor()
        cur.execute("SELECT id FROM users WHERE email=?", (email,))
        if cur.fetchone():
            self.send_json({"error": "email_exists"}, 409)
            return

        salt = secrets.token_hex(16)
        pw_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        cur.execute("INSERT INTO users (email, pw_hash, salt) VALUES (?,?,?)", (email, pw_hash, salt))
        db.commit()
        user_id = cur.lastrowid

        token = secrets.token_hex(32)
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        cur.execute("INSERT INTO sessions (user_id, token, expires) VALUES (?,?,?)", (user_id, token, expires))
        db.commit()
        self.send_json({"ok": True, "user_id": user_id, "token": token, "email": email})

    def handle_login(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "invalid_json"}, 400)
            return
        email = body.get("email", "").strip().lower()
        password = body.get("password", "")
        if not email or not password:
            self.send_json({"error": "invalid_input"}, 400)
            return

        cur = db.cursor()
        cur.execute("SELECT id, pw_hash, salt FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        if not row:
            self.send_json({"error": "invalid_credentials"}, 401)
            return
        user_id, pw_hash, salt = row
        if hashlib.sha256((password + salt).encode()).hexdigest() != pw_hash:
            self.send_json({"error": "invalid_credentials"}, 401)
            return

        token = secrets.token_hex(32)
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        cur.execute("INSERT INTO sessions (user_id, token, expires) VALUES (?,?,?)", (user_id, token, expires))
        db.commit()
        self.send_json({"ok": True, "user_id": user_id, "token": token, "email": email})

    # ── 数据端点 ──
    def handle_get_entries(self):
        user_id = self._check_token()
        if not user_id:
            self.send_json({"error": "unauthorized"}, 401)
            return
        cur = db.cursor()
        cur.execute("SELECT id, text, prompt, date, edited_at, thread FROM entries WHERE user_id=? ORDER BY date DESC", (user_id,))
        rows = cur.fetchall()
        entries = [{"id": r[0], "text": r[1], "prompt": r[2], "date": r[3], "edited_at": r[4], "thread": json.loads(r[5] if r[5] else "[]")} for r in rows]
        self.send_json(entries)

    def handle_save_entry(self):
        user_id = self._check_token()
        if not user_id:
            self.send_json({"error": "unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "invalid_json"}, 400)
            return

        eid = body.get("id")
        text = body.get("text", "")
        prompt = body.get("prompt")
        date = body.get("date", datetime.now().isoformat())
        edited_at = body.get("edited_at")
        thread = json.dumps(body.get("thread", []), ensure_ascii=False)

        cur = db.cursor()
        cur.execute("SELECT id FROM entries WHERE id=? AND user_id=?", (eid, user_id))
        if cur.fetchone():
            cur.execute("UPDATE entries SET text=?, prompt=?, edited_at=?, thread=? WHERE id=? AND user_id=?", (text, prompt, edited_at, thread, eid, user_id))
        else:
            cur.execute("INSERT INTO entries (id, user_id, text, prompt, date, edited_at, thread) VALUES (?,?,?,?,?,?,?)", (eid, user_id, text, prompt, date, edited_at, thread))
        db.commit()
        self.send_json({"ok": True})

    def handle_delete_entry(self):
        user_id = self._check_token()
        if not user_id:
            self.send_json({"error": "unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self.send_json({"error": "invalid_json"}, 400)
            return
        eid = body.get("id")
        cur = db.cursor()
        cur.execute("DELETE FROM entries WHERE id=? AND user_id=?", (eid, user_id))
        db.commit()
        self.send_json({"ok": True})

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

    def handle_summarize(self):
        """AI 精炼用户回答，用于分享卡片（≤120字）。"""
        if not self._check_auth() and ACCESS_CODE:
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
            self.send_json({"error": "empty"}, 400)
            return

        sys = "你是一位编辑。用户进行了一段哲学对话，你需要梳理ta的核心思路，写成一段 ≤120 字的精炼总结。要求：1) 理清用户的思考脉络，用自然的衔接连接各个观点 2) 保留逻辑力度和关键洞见，删去口语化的修饰和冗余 3) 如果原文包含多轮对话，提取贯穿始终的核心线索而不是只总结最后一句 4) 只输出精炼文本，不加引号、不解释、不评价。"
        user = text
        if prompt:
            user = f"用户最初回应的问题：「{prompt}」\n\n对话全文：\n{text}"

        try:
            summary = _deepseek([
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ], max_tokens=200)
            self.send_json({"ok": True, "summary": summary.strip()})
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
        source = body.get("source", "")
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
        reply = self.generate_reply(text, prompt, history, source)
        if reply:
            self.send_json({"ok": True, "chars": len(text), "reply": reply})
        else:
            self.send_json({"ok": True, "chars": len(text), "reply_fallback": True})

    def generate_reply(self, text, prompt, history=None, source=None):
        """Use DeepSeek API to generate a philosophical reply."""
        if not DEEPSEEK_KEY:
            print("  ⚠ 未设置 DEEPSEEK_API_KEY，跳过 AI 回复")
            return None

        # 构建提示词：如果有来源标注，引导从该传统出发
        system = REPLY_SYSTEM_PROMPT
        if source and source.strip():
            system += f"\n\n注意：用户正在回应的问题来自 {source.strip()}。你可以从这个哲学传统或相关思想出发开始讨论，但不限于此——如果对话自然走向其他方向，顺其自然。"

        # 构建消息数组
        messages = [{"role": "system", "content": system}]

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sizai-Auth, X-Sizai-Token")
        self.end_headers()

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            print(f"  → API 请求: {args[0]}")


# ── 初始化 SQLite 数据库 ──
def _init_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, salt TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))")
    db.execute("CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, token TEXT UNIQUE NOT NULL, expires TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))")
    db.execute("CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL, prompt TEXT, date TEXT, edited_at TEXT, thread TEXT DEFAULT '[]', FOREIGN KEY(user_id) REFERENCES users(id))")
    db.commit()
    return db

db = _init_db()

# ── Gist 备份/恢复 ──
def _backup_to_gist():
    """将 SQLite 数据库备份到 GitHub Gist。"""
    if not GIST_TOKEN or not GIST_ID:
        return
    try:
        import base64
        with open(DB_PATH, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")
        body = json.dumps({
            "files": {"sizai.db": {"content": content}}
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            data=body, method="PATCH",
            headers={
                "Authorization": f"Bearer {GIST_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        urllib.request.urlopen(req, timeout=15)
        print("  ✓ 已备份到 Gist")
    except Exception as e:
        print(f"  ⚠ Gist 备份失败: {e}")

def _restore_from_gist():
    """从 GitHub Gist 恢复 SQLite 数据库。"""
    if not GIST_TOKEN or not GIST_ID:
        return False
    try:
        import base64
        req = urllib.request.Request(
            f"https://api.github.com/gists/{GIST_ID}",
            headers={
                "Authorization": f"Bearer {GIST_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            gist = json.loads(resp.read().decode("utf-8"))
        file_data = gist.get("files", {}).get("sizai.db", {})
        if file_data and file_data.get("content"):
            with open(DB_PATH, "wb") as f:
                f.write(base64.b64decode(file_data["content"]))
            print("  ✓ 已从 Gist 恢复数据库")
            return True
    except Exception as e:
        print(f"  ⚠ Gist 恢复失败: {e}")
    return False

# 每 5 分钟自动备份
import threading, time
def _auto_backup():
    while True:
        time.sleep(300)
        _backup_to_gist()
threading.Thread(target=_auto_backup, daemon=True).start()

if __name__ == "__main__":
    # 启动时尝试恢复，然后重新打开 DB
    if _restore_from_gist():
        db.close()
        db = _init_db()
        print("  ✓ 数据库已从 Gist 恢复")
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
