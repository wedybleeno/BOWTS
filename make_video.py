import os
import time
import argparse
import datetime
from google import genai

def generate_video(prompt, out_dir):
    # Убедись, что у тебя стоит GOOGLE_API_KEY в переменных окружения
    client = genai.Client()

    print(f"[INFO] Запрос модели: veo-2.0-generate-001")
    operation = client.models.generate_videos(
        model="veo-2.0-generate-001",
        prompt=prompt
    )

    # Ждём, пока генерация завершится
    while not operation.done:
        print("[INFO] Жду завершения генерации...")
        time.sleep(10)
        operation = client.operations.get(operation)

    # Сохраняем результат
    video = operation.response.generated_videos[0]
    client.files.download(file=video.video)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"veo2_{ts}.mp4")
    video.video.save(out_path)

    print(f"[SUCCESS] Видео сохранено: {out_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True, help="Описание видео")
    parser.add_argument("--out_dir", type=str, default="videos", help="Папка для сохранения")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    generate_video(args.prompt, args.out_dir)
