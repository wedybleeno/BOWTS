#!/usr/bin/env python3
import os, re, sqlite3, asyncio, tempfile, json
from datetime import datetime
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument

API_ID   = int(os.getenv("TG_API_ID"))
API_HASH = os.getenv("TG_API_HASH")
SESSION  = os.getenv("TG_SESSION", "music_user")
WATCH_CHAT = os.getenv("WATCH_CHAT", "@MyMusicBot")  # ваш диалог с музыкальным ботом
DB = os.getenv("DB_PATH", "tracks.db")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db(); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS tracks(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        msg_id INTEGER NOT NULL,
        artist TEXT, title TEXT, filename TEXT, duration INTEGER,
        size INTEGER, mime TEXT,
        norm TEXT, raw TEXT, ts TEXT
    )""")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS u1 ON tracks(chat_id, msg_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS i_norm ON tracks(norm)")
    con.commit(); con.close()

def norm_key(artist, title, filename):
    base = " ".join(filter(None, [
        (artist or ""), (title or ""), (filename or "")
    ])).lower()
    base = re.sub(r"[_\-\.\[\]\(\)]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base

def meta_from_msg(m):
    artist = title = filename = None
    duration = size = None
    mime = None
    if isinstance(m.media, MessageMediaDocument) and m.document:
        mime = m.document.mime_type
        size = sum(a.size for a in m.document.attributes if hasattr(a, "size")) or None
        for a in m.document.attributes:
            if hasattr(a, "file_name") and a.file_name:
                filename = a.file_name
            if hasattr(a, "title") and a.title:
                title = a.title
            if hasattr(a, "performer") and a.performer:
                artist = a.performer
            if hasattr(a, "duration") and a.duration:
                duration = a.duration
    # часто artist - title в подписи
    txt = (m.message or "")[:400]
    if not artist or not title:
        mt = re.search(r"(?P<artist>.+?)\s*[-–]\s*(?P<title>.+)", txt)
        if mt:
            artist = artist or mt.group("artist").strip()
            title  = title  or mt.group("title").strip()
    return artist, title, filename, duration, size, mime, txt

async def main():
    init_db()
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()  # в первый запуск спросит код/пароль

    # первичная индексация истории по желанию:
    async for m in client.iter_messages(WATCH_CHAT, limit=1000):  # увеличьте при надобности
        if m.media and isinstance(m.media, MessageMediaDocument):
            artist, title, filename, duration, size, mime, txt = meta_from_msg(m)
            key = norm_key(artist, title, filename)
            con = db(); cur = con.cursor()
            cur.execute("""INSERT OR IGNORE INTO tracks
                (chat_id,msg_id,artist,title,filename,duration,size,mime,norm,raw,ts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (m.chat_id, m.id, artist, title, filename, duration, size, mime, key, txt, datetime.utcnow().isoformat()))
            con.commit(); con.close()

    @client.on(events.NewMessage(chats=[WATCH_CHAT]))
    async def handler(ev):
        m = ev.message
        if m.media and isinstance(m.media, MessageMediaDocument):
            artist, title, filename, duration, size, mime, txt = meta_from_msg(m)
            key = norm_key(artist, title, filename)
            con = db(); cur = con.cursor()
            cur.execute("""INSERT OR IGNORE INTO tracks
                (chat_id,msg_id,artist,title,filename,duration,size,mime,norm,raw,ts)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (ev.chat_id, m.id, artist, title, filename, duration, size, mime, key, txt, datetime.utcnow().isoformat()))
            con.commit(); con.close()

    # мини-RPC через stdin/stdout: читаем JSON-команды от нашего веб-API
    async def rpc_loop():
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, input)
            try:
                req = json.loads(line)
                if req.get("cmd") == "download_best":
                    q = req.get("q","").lower().strip()
                    con = db(); cur = con.cursor()
                    cur.execute("""SELECT * FROM tracks WHERE norm LIKE ? ORDER BY id DESC LIMIT 1""", (f"%{q}%",))
                    row = cur.fetchone(); con.close()
                    if not row:
                        print(json.dumps({"ok": False, "error": "not_found"})); continue
                    msg = await client.get_messages(row["chat_id"], ids=row["msg_id"])
                    tmp = tempfile.mkstemp(suffix=".mp3")[1]
                    await client.download_media(msg, file=tmp)
                    print(json.dumps({"ok": True, "path": tmp,
                                      "artist": row["artist"], "title": row["title"]}))
                else:
                    print(json.dumps({"ok": False, "error": "unknown_cmd"}))
            except Exception as e:
                print(json.dumps({"ok": False, "error": str(e)}))

    print("Listening & ready for RPC…")
    await asyncio.gather(client.run_until_disconnected(), rpc_loop())

if __name__ == "__main__":
    asyncio.run(main())
