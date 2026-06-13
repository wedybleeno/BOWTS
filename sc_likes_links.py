#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from yt_dlp import YoutubeDL

def main():
    if len(sys.argv) < 2:
        print("Использование: python sc_likes_links.py <url_на_likes>")
        sys.exit(1)

    url = sys.argv[1]

    ydl_opts = {
        "quiet": False,              # показывать ошибки
        "extract_flat": True,        # не качаем, только ссылки
        "skip_download": True,
        "dump_single_json": True,    # выдать всё как JSON
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info:
            print("❌ Не удалось получить список лайков")
            return

        entries = info.get("entries", [])
        print(f"📄 Найдено {len(entries)} треков")
        with open("likes.txt", "w", encoding="utf-8") as f:
            for e in entries:
                if not e:
                    continue
                track_url = e.get("url") or e.get("webpage_url")
                if track_url:
                    f.write(track_url + "\n")
                    print(track_url)

if __name__ == "__main__":
    main()
