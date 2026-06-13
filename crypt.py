import sys
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from aiohttp import ClientSession
from slugify import slugify
from rapidfuzz import process, fuzz
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

# Устанавливаем политику событий для Windows
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TG_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TG_TOKEN или TELEGRAM_TOKEN не задан в переменных окружения или .env")
COIN_LIST_FILE = Path("coins.json")
API = "https://api.coingecko.com/api/v3"

# === Проверка, нужно ли обновить список монет ===
def need_update(file: Path, max_age_hours=6):
    if not file.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(file.stat().st_mtime)
    return age > timedelta(hours=max_age_hours)

# === Загрузка списка монет с автообновлением ===
async def load_coins():
    if not need_update(COIN_LIST_FILE, max_age_hours=6):
        return json.loads(COIN_LIST_FILE.read_text(encoding="utf-8"))

    async with ClientSession() as s:
        async with s.get(f"{API}/coins/list") as r:
            r.raise_for_status()
            coins = await r.json()
            COIN_LIST_FILE.write_text(json.dumps(coins, ensure_ascii=False))
            return coins

# === Построение индекса ===
def build_index(coins):
    index = {}
    for c in coins:
        keys = {c["id"], c["symbol"], c["name"], slugify(c["name"])}
        for key in {k.lower() for k in keys}:
            index.setdefault(key, []).append(c["id"])
    return index

# === Получение цены монеты ===
async def fetch_price(session, coin_id):
    url = f"{API}/simple/price"
    params = {
        "ids": coin_id,
        "vs_currencies": "usd,rub",
        "include_24hr_change": "true"
    }
    async with session.get(url, params=params) as r:
        r.raise_for_status()
        return await r.json()

# === Обработчик сообщений ===
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    coin_ids = context.bot_data["index"].get(text)

    async with ClientSession() as session:
        if coin_ids:
            coin_id = coin_ids[0]
            data = await fetch_price(session, coin_id)
            price = data.get(coin_id)
            if price:
                await update.message.reply_text(
                    f"💰 {coin_id.capitalize()} = ${price['usd']:.2f} (₽{price['rub']:.0f})\n"
                    f"📊 24ч: {price['usd_24h_change']:+.2f}%"
                )
                return

        # fuzzy-поиск
        best, score = process.extractOne(text, context.bot_data["all_keys"], scorer=fuzz.WRatio)
        if score >= 60:
            await update.message.reply_text(f"🤔 Вы имели в виду “{best}”?")
        else:
            await update.message.reply_text("❌ Не нашёл монету.")

# === Главная функция ===
def main():
    loop = asyncio.get_event_loop()
    coins = loop.run_until_complete(load_coins())
    index = build_index(coins)

    app = Application.builder().token(TOKEN).build()
    app.bot_data["index"] = index
    app.bot_data["all_keys"] = list(index.keys())
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    app.run_polling()  # НЕ async → не вызывает конфликтов

# === Запуск ===
if __name__ == "__main__":
    main()
