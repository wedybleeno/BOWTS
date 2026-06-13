# 🚀 Инструкции по развертыванию на GitHub

## Шаг 1: Подготовка к загрузке

### 1.1 Инициализация Git репозитория
```bash
# Инициализируем Git репозиторий
git init

# Добавляем все файлы (кроме исключенных в .gitignore)
git add .

# Создаем первый коммит
git commit -m "Initial commit: BOTS collection"
```

### 1.2 Проверка исключенных файлов
Убедитесь, что конфиденциальные файлы не попадут в репозиторий:
- `BOT_TOKEN`
- `GOOGLE_API_KEY`
- `user_session.session`
- `index.db`
- `result.json`
- `coins.json`

## Шаг 2: Создание приватного репозитория на GitHub

### 2.1 Создание репозитория
1. Перейдите на [GitHub.com](https://github.com)
2. Нажмите "New repository"
3. Введите название: `BOTS`
4. **ВАЖНО**: Выберите "Private" (приватный)
5. НЕ ставьте галочки на README, .gitignore, license
6. Нажмите "Create repository"

### 2.2 Связывание локального репозитория с GitHub
```bash
# Добавляем удаленный репозиторий (замените YOUR_USERNAME на ваше имя пользователя)
git remote add origin https://github.com/YOUR_USERNAME/BOTS.git

# Переименовываем основную ветку в main (современный стандарт)
git branch -M main

# Отправляем код на GitHub
git push -u origin main
```

## Шаг 3: Настройка безопасности

### 3.1 Создание файла с переменными окружения
Создайте файл `.env` (он уже в .gitignore):
```env
# Telegram Bot Token
TELEGRAM_TOKEN=your_telegram_bot_token_here

# Google API Key
GOOGLE_API_KEY=your_google_api_key_here

# SoundCloud Profile URL
SOUNDCLOUD_PROFILE_URL=https://soundcloud.com/your-username/likes
```

### 3.2 Настройка GitHub Secrets (опционально)
Если планируете использовать GitHub Actions:

1. Перейдите в Settings → Secrets and variables → Actions
2. Добавьте секреты:
   - `TELEGRAM_TOKEN`
   - `GOOGLE_API_KEY`

## Шаг 4: Проверка загрузки

### 4.1 Проверка файлов на GitHub
1. Перейдите в ваш репозиторий на GitHub
2. Убедитесь, что все файлы загружены
3. Проверьте, что конфиденциальные файлы НЕ загружены

### 4.2 Проверка приватности
1. Откройте репозиторий в режиме инкогнито
2. Убедитесь, что доступ закрыт

## Шаг 5: Дополнительные настройки

### 5.1 Настройка веток
```bash
# Создание ветки для разработки
git checkout -b develop

# Отправка ветки на GitHub
git push -u origin develop
```

### 5.2 Настройка защиты веток (опционально)
1. Перейдите в Settings → Branches
2. Добавьте правило для ветки `main`
3. Включите "Require pull request reviews"

## Шаг 6: Клонирование на других устройствах

### 6.1 Клонирование репозитория
```bash
# Клонируем приватный репозиторий
git clone https://github.com/YOUR_USERNAME/BOTS.git

# Переходим в папку проекта
cd BOTS

# Устанавливаем зависимости
pip install -r requirements.txt

# Создаем файл .env с вашими токенами
cp .env.example .env
# Отредактируйте .env файл с вашими данными
```

## 🔒 Важные моменты безопасности

1. **Никогда не коммитьте токены и ключи**
2. **Всегда используйте .env файлы для конфиденциальных данных**
3. **Регулярно обновляйте зависимости**
4. **Используйте приватные репозитории для личных проектов**

## 📞 Поддержка

Если возникли проблемы:
1. Проверьте, что все файлы в .gitignore
2. Убедитесь, что репозиторий приватный
3. Проверьте права доступа к репозиторию
