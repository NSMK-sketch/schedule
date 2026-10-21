# Расписание занятий

Полноценное веб-приложение для визуального формирования учебного расписания.
Объединяет лучшее из проектов `raspisan` и `schedule_app`.

## Возможности

- таблица расписания: дни × пары, две учебные недели;
- drag & drop занятий и дисциплин преподавателя;
- проверка конфликтов (группа, преподаватель, аудитория);
- копирование расписания с одной недели на другую;
- полный CRUD справочников: группы, преподаватели, дисциплины, аудитории;
- связь преподаватель ↔ дисциплины;
- печать расписания выбранной группы;
- роли: администратор редактирует расписание, преподаватель смотрит;
- светлая и тёмная тема;
- поиск и фильтр по группам.

## Запуск

```powershell
cd schedule
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python run.py
```

Откройте http://127.0.0.1:5050/

При первом запуске сайт показывает страницу установки: там задаются логин и пароль администратора и, если нужен, токен бота MAX. Встроенных логинов нет.

Для локальной отладки с автоперезагрузкой: `$env:FLASK_DEBUG="1"` перед `python run.py`.

## Docker

На этой машине в образ кладётся текущая база с занятиями. Встроенные учётные записи в образ не попадают.

```powershell
python -c "import sqlite3; from app.database import remove_default_credentials_from_path; src=sqlite3.connect(r'instance/schedule.db'); dst=sqlite3.connect(r'instance/schedule.seed.db'); src.backup(dst); dst.close(); src.close(); remove_default_credentials_from_path(r'instance/schedule.seed.db')"
docker compose up -d --build
```

Сайт: http://127.0.0.1:5050/

Данные контейнера лежат в томе `schedule-data` и сохраняются при пересборке. Повторный `up` не затирает уже скопированную базу. Страница установки появляется, пока в базе нет администратора.

За HTTPS-прокси задайте `COOKIE_SECURE=1` и `TRUST_PROXY=1`.

## Учётная запись

Пароль администратора задаётся на странице установки, а не в репозитории. Студенческое расписание открыто по адресу `/student`.

## Структура

```
schedule/
├── app/
│   ├── __init__.py          # фабрика приложения
│   ├── config.py
│   ├── database.py          # SQLite и миграции
│   ├── routes/              # auth, lessons, reference
│   └── services/            # бизнес-логика занятий и конфликтов
├── static/                  # SPA: app.js, style.css, print.*
├── templates/               # Jinja-оболочка и partials
├── tests/
└── run.py
```

## Что взято из исходных проектов

| Из `raspisan` | Из `schedule_app` |
|---------------|-------------------|
| Роли admin/teacher | Печать расписания группы |
| Копирование недели | Расширенные поля групп/аудиторий |
| Тёмная тема, SPA UX | Полноценный CRUD справочников |
| Service-слой конфликтов | Цвет карточки по преподавателю |
| SQLite без настройки | Пустая база до страницы установки |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `SECRET_KEY` | создаётся сам | секрет сессий Flask, файл `instance/secret_key` |
| `SEED_DEMO_DATA` | `0` | учебные примеры только для пустой базы |
| `COOKIE_SECURE` | `0` | `1`, если сайт открыт по HTTPS |
| `TRUST_PROXY` | `0` | `1` за nginx или Caddy |
| `MAX_BOT_TOKEN` | пусто | токен бота; иначе его спрашивает страница установки |

## API (кратко)

- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `GET /api/bootstrap` — все справочники одним запросом
- `GET/POST/PUT/DELETE /api/lessons` (+ `POST /api/lessons/copy-week`)
- `POST/PUT/DELETE /api/groups|teachers|subjects|classrooms`
- `PUT /api/teachers/<id>/subjects`
- `GET /print/<group_id>` — страница печати
