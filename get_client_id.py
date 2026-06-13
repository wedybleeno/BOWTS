import requests
import re
import json

def get_soundcloud_client_id():
    """
    Автоматически получает актуальный client_id с SoundCloud
    """
    try:
        # Получаем главную страницу SoundCloud
        print("Получаю главную страницу SoundCloud...")
        response = requests.get("https://soundcloud.com/", timeout=10)
        response.raise_for_status()
        
        # Ищем client_id в JavaScript коде
        content = response.text
        
        # Паттерны для поиска client_id
        patterns = [
            r'client_id["\']?\s*:\s*["\']([^"\']+)["\']',
            r'clientId["\']?\s*:\s*["\']([^"\']+)["\']',
            r'"client_id":"([^"]+)"',
            r'client_id=([^&\s]+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            if matches:
                client_id = matches[0]
                if len(client_id) > 20:  # Проверяем, что это похоже на client_id
                    print(f"Найден client_id: {client_id}")
                    return client_id
        
        print("Client ID не найден в HTML. Попробуем другой метод...")
        
        # Альтернативный метод - через API
        print("Пробуем получить через API...")
        api_response = requests.get("https://api-v2.soundcloud.com/", timeout=10)
        if api_response.status_code == 200:
            # Ищем в заголовках или теле ответа
            headers = dict(api_response.headers)
            for key, value in headers.items():
                if 'client' in key.lower() and 'id' in key.lower():
                    print(f"Найден в заголовке {key}: {value}")
                    return value
        
        return None
        
    except Exception as e:
        print(f"Ошибка при получении client_id: {e}")
        return None

def test_client_id(client_id):
    """Тестирует client_id на работоспособность"""
    if not client_id:
        return False
    
    try:
        test_url = f"https://api-v2.soundcloud.com/search?q=test&client_id={client_id}&limit=1"
        response = requests.get(test_url, timeout=10)
        return response.status_code == 200
    except:
        return False

def main():
    print("=== SoundCloud Client ID Extractor ===")
    
    # Пытаемся получить client_id
    client_id = get_soundcloud_client_id()
    
    if client_id:
        print(f"\nПолучен client_id: {client_id}")
        
        # Тестируем его
        print("Тестирую client_id...")
        if test_client_id(client_id):
            print("✅ Client ID работает!")
            
            # Сохраняем в файл
            with open("client_id.txt", "w") as f:
                f.write(client_id)
            print("Client ID сохранен в файл client_id.txt")
            
            # Обновляем основной скрипт
            update_main_script(client_id)
            
        else:
            print("❌ Client ID не работает")
    else:
        print("❌ Не удалось получить client_id")
        print("\nПопробуйте получить вручную:")
        print("1. Откройте https://soundcloud.com/")
        print("2. Нажмите F12 (Developer Tools)")
        print("3. Перейдите на вкладку Network")
        print("4. Обновите страницу")
        print("5. Найдите любой запрос к api-v2.soundcloud.com")
        print("6. В параметрах запроса найдите client_id")

def update_main_script(client_id):
    """Обновляет основной скрипт с новым client_id"""
    try:
        with open("soundcloud.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Заменяем первый client_id в списке
        content = re.sub(
            r'CLIENT_IDS = \[[\s\S]*?\]',
            f'CLIENT_IDS = [\n    "{client_id}",\n    "2t9loNQH90kzJcsFCODdigxfp325aq4z",\n    "a281614d7fedd1d13740523e6bd94d8e",\n    "02gUJC0hH2ct1EGOcYXQIzRFU91c72Ea",\n    "YOUR_CLIENT_ID_HERE"  # Замените на свой, если нужно\n]',
            content
        )
        
        with open("soundcloud.py", "w", encoding="utf-8") as f:
            f.write(content)
        
        print("✅ Основной скрипт обновлен с новым client_id")
        
    except Exception as e:
        print(f"Ошибка при обновлении основного скрипта: {e}")

if __name__ == "__main__":
    main()

