#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import asyncio
import logging
from datetime import datetime
from typing import Optional, Tuple

from google import genai
from google.genai import types

from telegram import Update, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# ---------------------- НАСТРОЙКИ ----------------------
# Ключи берём из переменных окружения
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_TOKEN")

# Имя модели Veo; при необходимости поменяй на актуальное
VEO_MODEL = "veo-3.0-generate-preview"
IMAGEN_MODEL = "imagen-3.0-generate-002"

# Пауза между опросами статуса операции (сек)
POLL_INTERVAL = 10

# Папка для временных файлов
OUT_DIR = "out"
os.makedirs(OUT_DIR, exist_ok=True)

# Лимит длины промпта
MAX_PROMPT_LEN = 2000

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("veo_bot")

# Клиент Google GenAI
if not GOOGLE_API_KEY:
    raise RuntimeError("GOOGLE_API_KEY пуст. Установи переменную окружения GOOGLE_API_KEY.")
genai_client = genai.Client(api_key=GOOGLE_API_KEY)


# ---------------------- УТИЛИТЫ ----------------------
def sanitize_filename(text: str, suffix: str = "mp4") -> str:
    base = re.sub(r"[^\w\-]+", "_", text.strip())[:60] or "video"
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return os.path.join(OUT_DIR, f"{base}_{ts}.{suffix}")


async def poll_operation_until_done(op) -> any:
    """Ожидаем завершения операции Veo/Imagen."""
    while not getattr(op, "done", False):
        await asyncio.sleep(POLL_INTERVAL)
        op = genai_client.operations.get(op.name)
    return op


def parse_neg_from_args(args: list[str]) -> Tuple[str, Optional[str]]:
    """Парсер /veoadv: /veoadv <промпт> --neg="cartoon, low quality" """
    joined = " ".join(args).strip()
    m = re.search(r'--neg=(?P<q>"[^"]*"|\'[^\']*\'|[^\s]+)', joined)
    neg = None
    if m:
        raw = m.group("q")
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            neg = raw[1:-1]
        else:
            neg = raw
        prompt = (joined[:m.start()] + joined[m.end():]).strip()
    else:
        prompt = joined
    return prompt, (neg or None)


async def send_progress_ping(msg, dots=3):
    """Прогресс: добавляем точки в сообщении."""
    for i in range(dots):
        await asyncio.sleep(5)
        try:
            await msg.edit_text(msg.text_markdown_v2 + ".")
        except Exception:
            break


# ---------------------- ОБЁРТКИ ГЕНЕРАЦИИ ----------------------
async def generate_video_text(prompt: str) -> str:
    if not prompt or len(prompt) > MAX_PROMPT_LEN:
        raise ValueError("Промпт пуст или слишком длинный.")
    op = genai_client.models.generate_videos(model=VEO_MODEL, prompt=prompt)
    op = await poll_operation_until_done(op)
    video = op.response.generated_videos[0]
    outfile = sanitize_filename(prompt)
    genai_client.files.download(file=video.video, path=outfile)
    return outfile


async def generate_video_with_image_seed(prompt: str) -> str:
    if not prompt or len(prompt) > MAX_PROMPT_LEN:
        raise ValueError("Промпт пуст или слишком длинный.")
    img = genai_client.models.generate_images(model=IMAGEN_MODEL, prompt=prompt)
    seed_image = img.generated_images[0].image
    op = genai_client.models.generate_videos(model=VEO_MODEL, prompt=prompt, image=seed_image)
    op = await poll_operation_until_done(op)
    video = op.response.generated_videos[0]
    outfile = sanitize_filename(prompt)
    genai_client.files.download(file=video.video, path=outfile)
    return outfile


async def generate_video_adv(prompt: str, negative_prompt: Optional[str]) -> str:
    if not prompt or len(prompt) > MAX_PROMPT_LEN:
        raise ValueError("Промпт пуст или слишком длинный.")
    cfg = types.GenerateVideosConfig()
    if negative_prompt:
        cfg.negative_prompt = negative_prompt
    op = genai_client.models.generate_videos(model=VEO_MODEL, prompt=prompt, config=cfg)
    op = await poll_operation_until_done(op)
    video = op.response.generated_videos[0]
    outfile = sanitize_filename(prompt)
    genai_client.files.download(file=video.video, path=outfile)
    return outfile


# ---------------------- ХЕНДЛЕРЫ ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я бот для генерации видео через Veo 3.\n\n"
        "Команды:\n"
        "• /veo <промпт>\n"
        "• /veoimg <промпт>\n"
        "• /veoadv <промпт> --neg=\"cartoon, low quality\""
    )
    await update.message.reply_text(text)


async def veo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Используй: /veo <описание сцены>")
    prompt = " ".join(context.args).strip()
    msg = await update.message.reply_text("Генерирую видео через Veo…")
    asyncio.create_task(send_progress_ping(msg))
    try:
        outfile = await generate_video_text(prompt)
        await update.message.reply_video(video=InputFile(outfile), caption="Готово ✅")
    except Exception as e:
        log.exception("veo_cmd failed")
        await msg.edit_text(f"Ошибка: {e}")


async def veoimg_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Используй: /veoimg <описание сцены>")
    prompt = " ".join(context.args).strip()
    msg = await update.message.reply_text("Сначала Imagen, потом Veo…")
    asyncio.create_task(send_progress_ping(msg))
    try:
        outfile = await generate_video_with_image_seed(prompt)
        await update.message.reply_video(video=InputFile(outfile), caption="Готово ✅")
    except Exception as e:
        log.exception("veoimg_cmd failed")
        await msg.edit_text(f"Ошибка: {e}")


async def veoadv_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text('Используй: /veoadv <промпт> --neg="cartoon, low quality"')
    prompt, neg = parse_neg_from_args(context.args)
    if not prompt:
        return await update.message.reply_text("Пустой промпт.")
    msg = await update.message.reply_text(
        f"Генерирую видео…\n" + (f"negative_prompt: `{neg}`" if neg else "без negative_prompt"),
        parse_mode=ParseMode.MARKDOWN,
    )
    asyncio.create_task(send_progress_ping(msg))
    try:
        outfile = await generate_video_adv(prompt, neg)
        await update.message.reply_video(video=InputFile(outfile), caption="Готово ✅")
    except Exception as e:
        log.exception("veoadv_cmd failed")
        await msg.edit_text(f"Ошибка: {e}")


# ---------------------- MAIN ----------------------
def main():
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN пуст. Установи переменную окружения TELEGRAM_BOT_TOKEN.")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("veo", veo_cmd))
    app.add_handler(CommandHandler("veoimg", veoimg_cmd))
    app.add_handler(CommandHandler("veoadv", veoadv_cmd))
    log.info("Bot started.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
