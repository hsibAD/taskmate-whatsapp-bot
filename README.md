# TaskMate

TaskMate — WhatsApp-бот для ведения задач, напоминаний и обработки приглашений,
которые приходят по электронной почте. Бот понимает сообщения на русском и
английском языках, уточняет недостающие данные и хранит время с учётом часового
пояса пользователя.

## Возможности

- создание задач обычным сообщением;
- задачи с точным сроком или без срока;
- низкий, обычный и высокий приоритет;
- несколько предупреждений и уведомление непосредственно в момент задачи;
- завершение, удаление и перенос задач;
- дневные, недельные и месячные сводки;
- повторяющиеся задачи;
- смена почты и часового пояса без изменения старых сроков;
- импорт встреч из Gmail;
- разбор ICS и обычного текста письма;
- подтверждение почтовых событий через WhatsApp;
- интерактивное меню WhatsApp с быстрыми действиями;
- русский и английский интерфейс.

## Примеры сообщений

### Создание задач

```text
Напомни завтра в 15:00 позвонить врачу
Добавь сдать отчёт в следующий понедельник в 3 часа дня
Добавь завтра встречу с администратором в час дня напомни за 4 часа это важно
Создай задачу купить батарейки без срока
Добавь важно оплатить налог в пятницу в 10:30
```

Если в сообщении нет нужных сведений, бот продолжит диалог:

```text
Пользователь: Добавь завтра позвонить в акимат
Бот: Во сколько выполнить задачу?

Пользователь: В 11 утра
Бот: За сколько предупредить?

Пользователь: За день и за полтора часа
Бот: Создано: позвонить в акимат — 30.07.2026 11:00.
     Напоминания: за 1 день, за 1 час 30 минут и в момент задачи.
```

### Управление задачами

```text
Задачи
Выполнила позвонить врачу
Удали купить батарейки
Перенеси задачу позвонить Кале на час позже
Перенеси встречу на завтра в 14:00
Сводка на неделю
```

Если найдено несколько задач с одинаковым названием, бот показывает дату и
время каждой задачи:

```text
Выберите задачу:
1. позвонить врачу — 30.07.2026 10:00
2. позвонить врачу — 03.08.2026 15:00
```

### Напоминания

Поддерживаются естественные формулировки:

```text
за 30 минут
за полчаса
за полтора часа
за день и за час
за 2 часа и за 15 минут
только в момент задачи
по умолчанию
```

### Настройки

```text
Смени часовой пояс на Париж
Смени часовой пояс на Europe/Paris
Замени почту на new@example.com
Какие у тебя возможности
Как отправить тебе письмо?
```

Старые задачи сохраняют исходные сроки и часовой пояс. Новые задачи создаются
по текущему часовому поясу пользователя.

## Задачи и встречи из писем

Каждый пользователь привязывает свою почту с помощью одноразового кода. После
подтверждения письма с этого адреса можно отправлять на почту бота.

Данные события можно написать прямо в теме:

```text
Встреча с клиентом 3 августа в 15:00
```

Или в тексте письма:

```text
Приглашаем на презентацию проекта.
Дата: 3 августа 2026 года
Время: 15:00
Место: конференц-зал
```

Файл `.ics` необязателен. Если он приложен, бот использует его как наиболее
точный источник. Если даты или времени не хватает, бот задаёт уточняющий вопрос
в WhatsApp. Событие добавляется в список только после ответа `ДА`.

## Архитектура

```text
WhatsApp Cloud API ─┐
                    ├─> FastAPI ─> PostgreSQL
Gmail + Pub/Sub ────┘       │
                            └─> Redis ─> Celery worker
                                         ├─ напоминания
                                         ├─ повторяющиеся задачи
                                         └─ обработка писем
```

Состав проекта:

- **FastAPI** — webhook Meta, webhook Pub/Sub и служебные endpoints;
- **PostgreSQL** — пользователи, задачи, письма и состояния диалогов;
- **Redis + Celery** — фоновые задания и планировщик;
- **Gmail API + Pub/Sub** — получение новых писем;
- **Caddy** — HTTPS и reverse proxy;
- **Docker Compose** — локальный запуск и развёртывание на VPS.

## Требования

- Docker Engine и Docker Compose;
- домен с доступом по HTTPS;
- Meta Business App с WhatsApp Cloud API;
- Google Cloud project с Gmail API и Pub/Sub;
- OAuth Desktop client для почты бота;
- PostgreSQL и Redis запускаются через Compose.

## Быстрый запуск

1. Склонируйте репозиторий:

   ```bash
   git clone https://github.com/hsibAD/taskmate-whatsapp-bot.git
   cd taskmate-whatsapp-bot
   ```

2. Создайте файл окружения:

   ```bash
   cp .env.example .env
   ```

3. Заполните обязательные переменные в `.env`.

4. Запустите сервисы:

   ```bash
   docker compose up --build -d
   ```

5. Проверьте состояние:

   ```bash
   curl https://YOUR_DOMAIN/health
   curl https://YOUR_DOMAIN/ready
   ```

Ожидаемые ответы:

```json
{"status":"ok"}
{"status":"ready"}
```

## Настройка WhatsApp Cloud API

В Meta Developers:

1. создайте приложение типа Business;
2. подключите WhatsApp;
3. добавьте callback URL:

   ```text
   https://YOUR_DOMAIN/webhooks/whatsapp
   ```

4. укажите значение `META_VERIFY_TOKEN` из `.env`;
5. подпишитесь на событие `messages`;
6. скопируйте access token и phone number ID;
7. создайте и одобрите шаблон `task_reminder` с одним текстовым параметром.

Основные переменные:

```dotenv
META_VERIFY_TOKEN=
META_APP_SECRET=
META_ACCESS_TOKEN=
META_PHONE_NUMBER_ID=
META_API_VERSION=v25.0
META_REMINDER_TEMPLATE=task_reminder
```

В пределах 24-часового окна бот отправляет обычный текст. Вне этого окна
напоминания отправляются одобренным шаблоном Meta.

## Настройка Gmail

### 1. Google Cloud

Включите:

- Gmail API;
- Cloud Pub/Sub API.

Создайте topic:

```bash
gcloud pubsub topics create gmail-notifications \
  --project=YOUR_PROJECT_ID
```

Разрешите Gmail публиковать уведомления:

```bash
gcloud pubsub topics add-iam-policy-binding gmail-notifications \
  --project=YOUR_PROJECT_ID \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

Создайте push subscription:

```bash
gcloud pubsub subscriptions create gmail-push \
  --project=YOUR_PROJECT_ID \
  --topic=gmail-notifications \
  --push-endpoint=https://YOUR_DOMAIN/webhooks/gmail \
  --push-auth-service-account=YOUR_PUSH_SERVICE_ACCOUNT
```

### 2. OAuth

Скачайте OAuth Desktop client JSON и сохраните его локально:

```text
secrets/google-oauth.json
```

Создайте ключ шифрования:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Запишите результат в `GMAIL_TOKEN_ENCRYPTION_KEY`, затем выполните:

```bash
python scripts/gmail_oauth_setup.py
```

Скрипт откроет окно подтверждения Google и сохранит зашифрованный токен в
`secrets/google-oauth.json.token`.

### 3. Gmail watch

После запуска сервисов зарегистрируйте наблюдение:

```bash
SERVICE_TOKEN_VALUE="$(sed -n 's/^SERVICE_TOKEN=//p' .env)"

curl -X POST https://YOUR_DOMAIN/internal/gmail/watch \
  -H "Authorization: Bearer ${SERVICE_TOKEN_VALUE}"
```

Для fish shell:

```fish
set SERVICE_TOKEN_VALUE (sed -n 's/^SERVICE_TOKEN=//p' .env)

curl -X POST https://YOUR_DOMAIN/internal/gmail/watch \
  -H "Authorization: Bearer $SERVICE_TOKEN_VALUE"
```

## Переменные окружения

Полный список находится в [.env.example](.env.example).

Ключевые группы:

- `DATABASE_URL`, `POSTGRES_PASSWORD`, `REDIS_URL`;
- `META_*` — WhatsApp Cloud API;
- `GMAIL_*` — Gmail API и Pub/Sub;
- `SERVICE_TOKEN` — закрытые служебные endpoints;
- `DEFAULT_REMINDERS_MINUTES` — стандартные интервалы;
- `OPENAI_*` — необязательный семантический разбор свободных формулировок.

Критичные даты, права доступа и принадлежность задач всегда проверяются
сервером независимо от внешнего парсера.

## Тесты

Установите зависимости для разработки:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Запустите:

```bash
ruff check app tests
pytest
```

Ручные сценарии WhatsApp, Gmail и напоминаний собраны в
[TEST_CASES.txt](TEST_CASES.txt).

## Резервное копирование

Создать дамп PostgreSQL:

```bash
docker compose exec db sh /backup/backup.sh
```

Для production запускайте резервное копирование по расписанию и переносите
дампы во внешнее зашифрованное хранилище.

## Безопасность

- webhook Meta проверяется по подписи приложения;
- Pub/Sub push проверяется по OIDC audience;
- email связывается с пользователем только после OTP;
- задача всегда выбирается с фильтром по владельцу;
- повторная доставка webhook и писем дедуплицируется;
- OAuth-токен Gmail хранится в зашифрованном виде;
- полные тексты писем не сохраняются после обработки;
- секреты и локальные OAuth-файлы исключены из Git.

Никогда не добавляйте в репозиторий `.env`, содержимое `secrets/`, дампы базы
данных или production-токены.

## Служебные endpoints

| Method | Path | Назначение |
|---|---|---|
| `GET` | `/health` | состояние API |
| `GET` | `/ready` | готовность API и базы |
| `GET` | `/metrics` | метрики, требуется service token |
| `GET/POST` | `/webhooks/whatsapp` | Meta webhook |
| `POST` | `/webhooks/gmail` | Pub/Sub push |
| `POST` | `/internal/gmail/watch` | регистрация Gmail watch |
