# pip install python-telegram-bot==21.6
import os, re, sqlite3, time
from typing import List

from telegram import Update, InlineQueryResultCachedAudio, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
     ContextTypes, filters
)

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID  = int(os.getenv("CHANNEL_ID") or os.getenv("FORWARD_CHANNEL_ID") or "-1003056741244")   # -100...
ADMIN_ID    = int(os.getenv("ADMIN_ID", "0"))
DB_PATH     = os.getenv("DB_PATH", "index.db")

# ---------- БАЗА ----------
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db(); cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        type TEXT,
        title TEXT,
        performer TEXT,
        caption TEXT,
        text TEXT,
        audio_file_id TEXT,
        duration INTEGER,
        blob TEXT,
        created_at INTEGER
    )""")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique ON posts(chat_id, message_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_blob ON posts(blob)")
    con.commit(); con.close()

def normalize(*parts: str) -> str:
    s = " ".join([p or "" for p in parts])
    return re.sub(r"\s+", " ", s.lower()).strip()

def upsert_post(chat_id: int, message_id: int, type_: str,
                title: str, performer: str, caption: str, text: str,
                audio_file_id: str, duration: int):
    con = db(); cur = con.cursor()
    blob = normalize(title, performer, caption, text)
    cur.execute("""
        INSERT INTO posts(chat_id, message_id, type, title, performer, caption, text, audio_file_id, duration, blob, created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
          type=excluded.type, title=excluded.title, performer=excluded.performer,
          caption=excluded.caption, text=excluded.text, audio_file_id=excluded.audio_file_id,
          duration=excluded.duration, blob=excluded.blob
    """, (chat_id, message_id, type_, title, performer, caption, text, audio_file_id, duration, blob, int(time.time())))
    con.commit(); con.close()

def search_posts(query: str, limit: int = 10) -> List[sqlite3.Row]:
    tokens = [t for t in re.split(r"[^\w]+", query.lower()) if t]
    if not tokens: return []
    where = " AND ".join(["blob LIKE ?"] * len(tokens))
    params = [f"%{t}%" for t in tokens]
    con = db(); cur = con.cursor()
    cur.execute(f"SELECT * FROM posts WHERE {where} ORDER BY message_id DESC LIMIT ?", (*params, limit))
    rows = cur.fetchall(); con.close(); return rows

def suggest_like(query: str, limit: int = 10) -> List[sqlite3.Row]:
    q = query.lower().strip()
    if not q: return []
    con = db(); cur = con.cursor()
    cur.execute("SELECT * FROM posts WHERE blob LIKE ? ORDER BY message_id DESC LIMIT ?", (f"%{q}%", limit))
    rows = cur.fetchall(); con.close(); return rows

# ---------- ХЭНДЛЕРЫ ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Ищу по каналу.\n"
        "Примеры: /find техник  •  /find паша техник\n"
        "Если точных совпадений нет — дам похожие."
    )

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ADMIN_ID and (not update.effective_user or update.effective_user.id != ADMIN_ID):
        return
    con = db(); cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM posts"); total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM posts WHERE type='audio'"); aud = cur.fetchone()[0]
    con.close()
    await update.effective_message.reply_text(f"В индексе: {total} записей (аудио: {aud})")

async def do_find(query: str, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = search_posts(query, limit=10)
    if rows:
        for r in rows:
            try:
                await ctx.bot.forward_message(
                    chat_id=update.effective_chat.id,
                    from_chat_id=r["chat_id"],
                    message_id=r["message_id"]
                )
            except Exception:
                if r["audio_file_id"]:
                    title = r["title"] or r["caption"] or r["text"] or "audio"
                    await update.effective_message.reply_audio(audio=r["audio_file_id"], title=title)
        if len(rows) == 10:
            await update.effective_message.reply_text("Показал 10 последних. Уточни запрос для точности.")
        return

    sug = suggest_like(query, limit=10)
    if sug:
        lines = []
        for r in sug:
            piece = r["title"] or r["performer"] or r["caption"] or r["text"] or ""
            lines.append("• " + (piece[:60] + "…") if len(piece) > 60 else piece)
        await update.effective_message.reply_text(
            "Точных совпадений нет. Похожие:\n" + "\n".join(lines)
        )
    else:
        await update.effective_message.reply_text("Ничего не нашёл 😕 Попробуй другое слово или фразу.")

async def find_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args).strip()
    if not query:
        await update.effective_message.reply_text("Напиши: /find <запрос>")
        return
    await do_find(query, update, ctx)

async def find_edited(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.edited_message.text or "").strip()
    if text.startswith("/find"):
        query = text.split(" ", 1)[1] if " " in text else ""
        if not query:
            await update.edited_message.reply_text("Напиши: /find <запрос>")
            return
        await do_find(query, update, ctx)

async def index_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or msg.chat.type != "channel" or msg.chat.id != CHANNEL_ID:
        return

    chat_id = msg.chat_id
    message_id = msg.message_id
    caption = msg.caption or ""
    text = msg.text or ""
    title = performer = audio_file_id = None
    duration = None
    type_ = "text"

    if msg.audio:
        type_ = "audio"; title = msg.audio.title; performer = msg.audio.performer
        audio_file_id = msg.audio.file_id; duration = msg.audio.duration
    elif msg.voice:
        type_ = "audio"; title = "voice"; performer = ""
        audio_file_id = msg.voice.file_id; duration = msg.voice.duration
    elif msg.document and (msg.document.mime_type or "").startswith("audio/"):
        type_ = "audio"; title = msg.document.file_name; performer = ""
        audio_file_id = msg.document.file_id

    upsert_post(chat_id, message_id, type_, title or "", performer or "",
                caption, text, audio_file_id or "", duration or 0)

async def index_forwarded(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.forward_from_chat:
        return
    if msg.forward_from_chat.id != CHANNEL_ID:
        return

    chat_id = msg.forward_from_chat.id
    message_id = msg.forward_from_message_id or msg.message_id
    caption = msg.caption or ""
    text = msg.text or ""
    title = performer = audio_file_id = None
    duration = None
    type_ = "text"

    if msg.audio:
        type_ = "audio"; title = msg.audio.title; performer = msg.audio.performer
        audio_file_id = msg.audio.file_id; duration = msg.audio.duration
    elif msg.voice:
        type_ = "audio"; title = "voice"; performer = ""
        audio_file_id = msg.voice.file_id; duration = msg.voice.duration
    elif msg.document and (msg.document.mime_type or "").startswith("audio/"):
        type_ = "audio"; title = msg.document.file_name; performer = ""
        audio_file_id = msg.document.file_id

    upsert_post(chat_id, message_id, type_, title or "", performer or "",
                caption, text, audio_file_id or "", duration or 0)
    await msg.reply_text("✅ Добавил в индекс.")

async def inline_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = (update.inline_query.query or "").strip()
    if not q: return
    rows = search_posts(q, limit=10)
    results = []
    for i, r in enumerate(rows):
        if r["audio_file_id"]:
            title = r["title"] or r["caption"] or r["text"] or "audio"
            results.append(
                InlineQueryResultCachedAudio(
                    id=str(i),
                    audio_file_id=r["audio_file_id"],
                    caption=(r["caption"] or r["text"] or ""),
                    title=title
                )
            )
        else:
            snippet = (r["title"] or r["performer"] or r["caption"] or r["text"] or "")[:80]
            results.append(
                InlineQueryResultArticle(
                    id=str(i),
                    title=snippet or "Открыть результаты",
                    input_message_content=InputTextMessageContent(f"/find {q}")
                )
            )
    await update.inline_query.answer(results=results, cache_time=0, is_personal=True)

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        raise SystemExit("Нужно задать BOT_TOKEN и CHANNEL_ID (-100...).")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Индексация постов из канала
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, index_channel))

    # Индексация пересланных постов
    app.add_handler(MessageHandler(filters.FORWARDED & filters.TEXT, index_forwarded))
    app.add_handler(MessageHandler(filters.FORWARDED & (filters.AUDIO | filters.VOICE | filters.Document.AUDIO), index_forwarded))

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("find", find_cmd))
    app.add_handler(CommandHandler("stats", stats))

    # Обработка редактированных сообщений
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.TEXT, find_edited))

    # Инлайн-поиск
    app.add_handler(InlineQueryHandler(inline_query))

    print("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
