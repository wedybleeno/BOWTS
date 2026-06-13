#!/usr/bin/env python3
"""
Скрипт для настройки Git и подготовки к загрузке на GitHub
"""

import subprocess
import os
import sys

def run_command(command):
    """Выполняет команду и возвращает результат"""
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def setup_git():
    """Настраивает Git конфигурацию"""
    print("=== Настройка Git конфигурации ===")
    
    # Запрашиваем данные пользователя
    print("\nВведите ваши данные для Git:")
    name = input("Имя пользователя: ").strip()
    email = input("Email: ").strip()
    
    if not name or not email:
        print("❌ Имя и email обязательны!")
        return False
    
    # Настраиваем Git
    commands = [
        f'git config --global user.name "{name}"',
        f'git config --global user.email "{email}"'
    ]
    
    for cmd in commands:
        success, stdout, stderr = run_command(cmd)
        if not success:
            print(f"❌ Ошибка выполнения команды: {cmd}")
            print(f"Ошибка: {stderr}")
            return False
    
    print("✅ Git конфигурация настроена")
    return True

def create_initial_commit():
    """Создает первый коммит"""
    print("\n=== Создание первого коммита ===")
    
    # Добавляем файлы
    success, stdout, stderr = run_command("git add .")
    if not success:
        print(f"❌ Ошибка добавления файлов: {stderr}")
        return False
    
    # Создаем коммит
    commit_message = "Initial commit: BOTS collection with SoundCloud scraper and various bots"
    success, stdout, stderr = run_command(f'git commit -m "{commit_message}"')
    if not success:
        print(f"❌ Ошибка создания коммита: {stderr}")
        return False
    
    print("✅ Первый коммит создан")
    return True

def show_next_steps():
    """Показывает следующие шаги"""
    print("\n" + "="*50)
    print("🎉 Настройка завершена!")
    print("="*50)
    print("\nСледующие шаги:")
    print("1. Создайте приватный репозиторий на GitHub:")
    print("   - Перейдите на https://github.com")
    print("   - Нажмите 'New repository'")
    print("   - Название: BOTS")
    print("   - Выберите 'Private'")
    print("   - НЕ ставьте галочки на README, .gitignore, license")
    print("   - Нажмите 'Create repository'")
    print("\n2. Свяжите локальный репозиторий с GitHub:")
    print("   git remote add origin https://github.com/YOUR_USERNAME/BOTS.git")
    print("   git branch -M main")
    print("   git push -u origin main")
    print("\n3. Создайте файл .env с вашими токенами:")
    print("   cp env.example .env")
    print("   # Отредактируйте .env файл")
    print("\n4. Проверьте, что конфиденциальные файлы НЕ загружены")

def main():
    """Основная функция"""
    print("🚀 Настройка Git для загрузки на GitHub")
    
    # Проверяем, что мы в Git репозитории
    if not os.path.exists(".git"):
        print("❌ Не найден .git каталог. Запустите 'git init' сначала.")
        return
    
    # Настраиваем Git
    if not setup_git():
        return
    
    # Создаем коммит
    if not create_initial_commit():
        return
    
    # Показываем следующие шаги
    show_next_steps()

if __name__ == "__main__":
    main()
