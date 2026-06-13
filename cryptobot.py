import sys
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import ClientSession
from slugify import slugify
import os
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters
import google.generativeai as genai
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# === НАСТРОЙКИ ===
TG_TOKEN = os.getenv("TG_TOKEN") or os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not TG_TOKEN:
    raise ValueError("TG_TOKEN не задан в переменных окружения или .env")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY не задан в переменных окружения или .env")

genai.configure(api_key=GEMINI_API_KEY)

COIN_LIST_FILE = Path("coins.json")
API = "https://api.coingecko.com/api/v3"

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# === Обновление списка монет ===
def need_update(file: Path, max_age_hours=6):
    if not file.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(file.stat().st_mtime)
    return age > timedelta(hours=max_age_hours)

async def load_coins():
    if not need_update(COIN_LIST_FILE):
        return json.loads(COIN_LIST_FILE.read_text(encoding="utf-8"))
    async with ClientSession() as s:
        async with s.get(f"{API}/coins/list") as r:
            r.raise_for_status()
            coins = await r.json()
            COIN_LIST_FILE.write_text(json.dumps(coins, ensure_ascii=False))
            return coins

def build_index(coins):
    index = {}
    for c in coins:
        keys = {c["id"], c["symbol"], c["name"], slugify(c["name"])}
        for key in {k.lower() for k in keys}:
            index.setdefault(key, []).append(c["id"])
    return index

# === Получение цены монеты ===
async def fetch_price(session, coin_id):
    async with session.get(
        f"{API}/simple/price",
        params={"ids": coin_id, "vs_currencies": "usd,rub", "include_24hr_change": "true"},
    ) as r:
        r.raise_for_status()
        return await r.json()

# === Запрос к Gemini ===
async def ask_gemini(prompt):
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    return response.text.strip()

# === Обработчик сообщений ===
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    all_ids = context.bot_data["valid_ids"]

    # Шлём в Gemini и просим определить криптовалюты
    gemini_prompt = f"""
Ты — Telegram-бот, помогающий с криптовалютой. 
Пользователь пишет тебе произвольную фразу. 
Твоя задача — понять, есть ли в этой фразе название какой-либо криптовалюты (даже с ошибкой, на русском, сленге и т.д.).

Если найдены монеты, ответь ТОЛЬКО в таком формате:
["bitcoin", "dogecoin"]

Если не уверен — скажи: "Я не понял, какую валюту ты имеешь в виду. Можешь уточнить?"

Фраза от пользователя: "{user_input}"
"""

    answer = await ask_gemini(gemini_prompt)
    print("[Gemini] Ответ:", answer)

    try:
        coin_ids = eval(answer)
        if not isinstance(coin_ids, list):
            raise ValueError("not list")
    except Exception:
        await update.message.reply_text(answer)
        return

    async with ClientSession() as session:
        lines = []
        for cid in coin_ids:
            if cid not in all_ids:
                lines.append(f"❓ Не знаю монету: {cid}")
                continue
            try:
                data = await fetch_price(session, cid)
                price = data[cid]
                lines.append(
                    f"💰 {cid.capitalize()} = ${price['usd']:.2f} (₽{price['rub']:.0f})\n"
                    f"📊 24ч: {price['usd_24h_change']:+.2f}%"
                )
            except Exception:
                lines.append(f"⚠️ Не удалось получить {cid}")

        await update.message.reply_text("\n\n".join(lines))

# === MAIN ===
def main():
    loop = asyncio.get_event_loop()
    coins = loop.run_until_complete(load_coins())
    index = build_index(coins)

    app = Application.builder().token(TG_TOKEN).build()
    app.bot_data["index"] = index
    app.bot_data["valid_ids"] = list(index.keys())

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.run_polling()

if __name__ == "__main__":
    main()
