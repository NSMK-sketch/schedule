"""Day substitutions: a draft sheet until it is published to students and MAX."""

import logging
import re
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.database import get_db
from app.services.max_client import MaxApiError, MaxClient


logger = logging.getLogger(__name__)

SCHOOL_TZ = timezone(timedelta(hours=7))
WEEKDAYS = (
    "",
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
)
WEEKDAY_TITLE = (
    "",
    "ПОНЕДЕЛЬНИК",
    "ВТОРНИК",
    "СРЕДА",
    "ЧЕТВЕРГ",
    "ПЯТНИЦА",
    "СУББОТА",
)
_NOTIFY_CHAT_KEY = "max_changes_chat_id"
_TEXT_LIMIT = 3800
_MAX_ROWS = 120
_MD_CHARS = "*_`[]~+^>#"
_ROOM_PREFIX = re.compile(r"(?i)^ауд\.?\s*")
_CHAT_ID = re.compile(r"-?\d{1,20}")


def school_today():
    return datetime.now(SCHOOL_TZ).date()


def _now_stamp():
    return datetime.now(SCHOOL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _norm_name(value):
    return " ".join(str(value or "").casefold().split())


def _clip(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _clean_room(value):
    text = _clip(value, 40)
    text = _ROOM_PREFIX.sub("", text).strip("() ")
    return text[:32]


def parse_periods(value):
    """Return period numbers from '3,4' or '1, 2'. '1,3' stays two periods, not a range."""
    text = str(value or "").strip()
    if not text:
        return None, "Укажите номера пар через запятую, например 3,4."
    if len(text) > 40:
        return None, "Слишком длинный список пар."
    chunks = re.split(r"[\s,;]+", text.replace(".", ","))
    periods = []
    for chunk in chunks:
        if not chunk:
            continue
        if not chunk.isdigit():
            return None, "Номера пар пишите через запятую, например 3,4."
        number = int(chunk)
        if number < 1 or number > 8:
            return None, "Пара должна быть от 1 до 8."
        if number not in periods:
            periods.append(number)
    if not periods:
        return None, "Укажите номера пар через запятую, например 3,4."
    return periods, None


def format_date(iso_date):
    year, month, day = str(iso_date).split("-")
    return f"{day}.{month}.{year}"


def subject_with_room(subject, room):
    subject = str(subject or "").strip()
    room = str(room or "").strip()
    if room and subject:
        return f"{subject} (ауд.{room})"
    if room:
        return f"ауд.{room}"
    return subject


def sheet_title(sheet_date, week, weekday):
    return (
        f"Замена на {format_date(sheet_date)}г "
        f"{week}-Я НЕДЕЛЯ ({WEEKDAY_TITLE[weekday]})"
    )


def _row_is_blank(raw):
    if not isinstance(raw, dict):
        return False
    fields = (
        "group_id",
        "group_name",
        "periods",
        "new_subject",
        "new_room",
        "new_teacher",
        "old_subject",
        "absent_teacher",
    )
    return all(not str(raw.get(field) or "").strip() for field in fields)


def _load_groups(db):
    rows = db.execute("SELECT id, name FROM groups_ref").fetchall()
    by_id = {row["id"]: row["name"] for row in rows}
    by_name = {_norm_name(row["name"]): row for row in rows}
    return by_id, by_name


def _parse_row(raw, index, groups_by_id, groups_by_name):
    if not isinstance(raw, dict):
        return None, f"Строка {index}: неверный формат."

    group_id = raw.get("group_id")
    group_name = _clip(raw.get("group_name"), 80)
    if group_id not in (None, ""):
        try:
            group_id = int(group_id)
        except (TypeError, ValueError):
            return None, f"Строка {index}: выберите группу из списка."
        if group_id not in groups_by_id:
            return None, f"Строка {index}: группа не найдена."
        group_name = groups_by_id[group_id]
    else:
        group_id = None
        matched = groups_by_name.get(_norm_name(group_name))
        if matched is not None:
            group_id = matched["id"]
            group_name = matched["name"]

    if not group_name:
        return None, f"Строка {index}: выберите группу."

    periods, error = parse_periods(raw.get("periods"))
    if error:
        return None, f"Строка {index}: {error}"

    new_subject = _clip(raw.get("new_subject"), 160)
    new_room = _clean_room(raw.get("new_room"))
    new_teacher = _clip(raw.get("new_teacher"), 80)
    old_subject = _clip(raw.get("old_subject"), 160)
    absent_teacher = _clip(raw.get("absent_teacher"), 80)
    if not any((new_subject, new_room, new_teacher, old_subject, absent_teacher)):
        return None, (
            f"Строка {index}: укажите, что будет вместо занятия, "
            "или кого заменяют."
        )

    return {
        "group_id": group_id,
        "group_name": group_name,
        "periods": periods,
        "periods_label": ",".join(str(number) for number in periods),
        "new_subject": new_subject,
        "new_room": new_room,
        "new_teacher": new_teacher,
        "old_subject": old_subject,
        "absent_teacher": absent_teacher,
    }, None


def _parse_sheet(data, db):
    if not isinstance(data, dict):
        return None, "Неверный формат."

    raw_date = str(data.get("sheet_date") or "").strip()
    try:
        sheet_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        return None, "Укажите дату замены."

    weekday = sheet_date.weekday() + 1
    if weekday > 6:
        return None, "На воскресенье замену создать нельзя."

    try:
        week = int(data.get("week"))
    except (TypeError, ValueError):
        week = 0
    if week not in (1, 2):
        return None, "Неделя должна быть 1 или 2."

    rows = data.get("rows")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return None, "Строки замены переданы неверно."
    if len(rows) > _MAX_ROWS:
        return None, f"В одном листе не больше {_MAX_ROWS} строк."

    groups_by_id, groups_by_name = _load_groups(db)
    parsed_rows = []
    for index, raw in enumerate(rows, start=1):
        if _row_is_blank(raw):
            continue
        parsed, error = _parse_row(raw, index, groups_by_id, groups_by_name)
        if error:
            return None, error
        parsed_rows.append(parsed)

    return {
        "sheet_date": sheet_date.isoformat(),
        "week": week,
        "weekday": weekday,
        "rows": parsed_rows,
    }, None


def _serialize_row(row):
    periods = [int(part) for part in str(row["periods"]).split(",") if part]
    new_subject = row["new_subject"] or ""
    new_room = row["new_room"] or ""
    new_teacher = row["new_teacher"] or ""
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        "periods": periods,
        "periods_label": row["periods"],
        "new_subject": new_subject,
        "new_room": new_room,
        "new_teacher": new_teacher,
        "old_subject": row["old_subject"] or "",
        "absent_teacher": row["absent_teacher"] or "",
        "new_subject_label": subject_with_room(new_subject, new_room),
        "cancelled": not new_subject and not new_room and not new_teacher,
    }


def _serialize_sheet(row, rows):
    payload = {
        "id": row["id"],
        "sheet_date": row["sheet_date"],
        "date_label": format_date(row["sheet_date"]),
        "week": row["week"],
        "weekday": row["weekday"],
        "weekday_label": WEEKDAYS[row["weekday"]],
        "status": row["status"],
        "title": sheet_title(row["sheet_date"], row["week"], row["weekday"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "published_at": row["published_at"],
        "last_notify_at": row["last_notify_at"],
        "last_notify_error": row["last_notify_error"] or "",
        "row_count": len(rows),
        "rows": [_serialize_row(item) for item in rows],
        "url": f"/changes/{row['id']}",
    }
    return payload


def _sheet_row(db, sheet_id):
    return db.execute(
        """
        SELECT
            id, sheet_date, week, weekday, status,
            created_at, updated_at, published_at,
            last_notify_at, last_notify_error
        FROM substitution_sheets
        WHERE id = ?
        """,
        (sheet_id,),
    ).fetchone()


def _rows_for(db, sheet_id):
    return db.execute(
        """
        SELECT
            id, sheet_id, sort_order, group_id, group_name, periods,
            new_subject, new_room, new_teacher, old_subject, absent_teacher
        FROM substitution_rows
        WHERE sheet_id = ?
        ORDER BY sort_order, id
        """,
        (sheet_id,),
    ).fetchall()


def get_sheet(sheet_id):
    db = get_db()
    row = _sheet_row(db, sheet_id)
    if row is None:
        return None
    return _serialize_sheet(row, _rows_for(db, sheet_id))


def list_sheets():
    rows = get_db().execute(
        """
        SELECT
            substitution_sheets.id,
            substitution_sheets.sheet_date,
            substitution_sheets.week,
            substitution_sheets.weekday,
            substitution_sheets.status,
            substitution_sheets.updated_at,
            substitution_sheets.published_at,
            (
                SELECT COUNT(*)
                FROM substitution_rows
                WHERE substitution_rows.sheet_id = substitution_sheets.id
            ) AS row_count
        FROM substitution_sheets
        ORDER BY substitution_sheets.sheet_date DESC, substitution_sheets.id DESC
        """
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sheet_date": row["sheet_date"],
            "date_label": format_date(row["sheet_date"]),
            "week": row["week"],
            "weekday": row["weekday"],
            "weekday_label": WEEKDAYS[row["weekday"]],
            "status": row["status"],
            "title": sheet_title(row["sheet_date"], row["week"], row["weekday"]),
            "updated_at": row["updated_at"],
            "published_at": row["published_at"],
            "row_count": row["row_count"],
            "url": f"/changes/{row['id']}",
        }
        for row in rows
    ]


def _insert_rows(db, sheet_id, rows):
    db.executemany(
        """
        INSERT INTO substitution_rows (
            sheet_id, sort_order, group_id, group_name, periods,
            new_subject, new_room, new_teacher, old_subject, absent_teacher
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                sheet_id,
                index,
                row["group_id"],
                row["group_name"],
                row["periods_label"],
                row["new_subject"],
                row["new_room"],
                row["new_teacher"],
                row["old_subject"],
                row["absent_teacher"],
            )
            for index, row in enumerate(rows)
        ],
    )


def create_sheet(data):
    db = get_db()
    parsed, error = _parse_sheet(data, db)
    if error:
        return None, error
    stamp = _now_stamp()
    cursor = db.execute(
        """
        INSERT INTO substitution_sheets (
            sheet_date, week, weekday, status, created_at, updated_at
        ) VALUES (?, ?, ?, 'draft', ?, ?)
        """,
        (parsed["sheet_date"], parsed["week"], parsed["weekday"], stamp, stamp),
    )
    _insert_rows(db, cursor.lastrowid, parsed["rows"])
    db.commit()
    return get_sheet(cursor.lastrowid), None


def update_sheet(sheet_id, data):
    db = get_db()
    current = _sheet_row(db, sheet_id)
    if current is None:
        return None, "Лист замены не найден."
    if current["status"] != "draft":
        return None, "Снимите лист с публикации, чтобы изменить его."
    parsed, error = _parse_sheet(data, db)
    if error:
        return None, error
    stamp = _now_stamp()
    db.execute(
        """
        UPDATE substitution_sheets
        SET sheet_date = ?, week = ?, weekday = ?, updated_at = ?
        WHERE id = ?
        """,
        (parsed["sheet_date"], parsed["week"], parsed["weekday"], stamp, sheet_id),
    )
    db.execute("DELETE FROM substitution_rows WHERE sheet_id = ?", (sheet_id,))
    _insert_rows(db, sheet_id, parsed["rows"])
    db.commit()
    return get_sheet(sheet_id), None


def delete_sheet(sheet_id):
    db = get_db()
    current = _sheet_row(db, sheet_id)
    if current is None:
        return False, "Лист замены не найден."
    db.execute("DELETE FROM substitution_sheets WHERE id = ?", (sheet_id,))
    db.commit()
    return True, None


def publish_sheet(sheet_id):
    db = get_db()
    current = _sheet_row(db, sheet_id)
    if current is None:
        return None, "Лист замены не найден."
    if current["status"] == "published":
        return None, "Лист уже опубликован."
    count = db.execute(
        "SELECT COUNT(*) FROM substitution_rows WHERE sheet_id = ?",
        (sheet_id,),
    ).fetchone()[0]
    if not count:
        return None, "Добавьте хотя бы одну строку замены."
    stamp = _now_stamp()
    db.execute(
        """
        UPDATE substitution_sheets
        SET status = 'published', published_at = ?, updated_at = ?,
            last_notify_error = ''
        WHERE id = ?
        """,
        (stamp, stamp, sheet_id),
    )
    db.commit()
    sheet = get_sheet(sheet_id)
    notice = notify_sheet(sheet)
    return {"sheet": get_sheet(sheet_id), "notify": notice}, None


def unpublish_sheet(sheet_id):
    db = get_db()
    current = _sheet_row(db, sheet_id)
    if current is None:
        return None, "Лист замены не найден."
    if current["status"] != "published":
        return None, "Лист ещё не опубликован."
    stamp = _now_stamp()
    db.execute(
        """
        UPDATE substitution_sheets
        SET status = 'draft', published_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (stamp, sheet_id),
    )
    db.commit()
    return get_sheet(sheet_id), None


def _setting(db, key):
    row = db.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    return "" if row is None else str(row["value"] or "").strip()


def _save_setting(db, key, value):
    if not value:
        db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        return
    db.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_notify_chat():
    return {"chat_id": _setting(get_db(), _NOTIFY_CHAT_KEY)}


def set_notify_chat(chat_id):
    text = str(chat_id or "").strip()
    if text and (not _CHAT_ID.fullmatch(text) or text in {"0", "-0"}):
        return None, "ID чата — это число. Его пришлёт бот по команде /chatid."
    db = get_db()
    _save_setting(db, _NOTIFY_CHAT_KEY, text)
    db.commit()
    return {"chat_id": text}, None


def site_origin():
    stored = _setting(get_db(), "public_url")
    if stored.startswith("https://") or stored.startswith("http://"):
        return stored.rstrip("/")
    return ""


def _md(value):
    text = str(value or "")
    for char in _MD_CHARS:
        text = text.replace(char, "")
    return " ".join(text.split())


def _row_message(row):
    group = _md(row["group_name"]) or "Группа"
    periods = row["periods_label"]
    pair = "пара" if len(row["periods"]) == 1 else "пары"
    old_bits = [
        bit
        for bit in (_md(row["old_subject"]), _md(row["absent_teacher"]))
        if bit
    ]
    if row["cancelled"]:
        lines = [f"**{group}**, {periods} {pair} — занятие снято"]
        if old_bits:
            lines.append("было: " + ", ".join(old_bits))
        return "\n".join(lines)

    subject = _md(row["new_subject_label"]) or "предмет не указан"
    teacher = _md(row["new_teacher"])
    line = f"**{group}**, {periods} {pair} — {subject}"
    if teacher:
        line += f", {teacher}"
    lines = [line]
    if old_bits:
        lines.append("вместо: " + ", ".join(old_bits))
    return "\n".join(lines)


def build_notice_messages(sheet, origin):
    """Readable MAX text plus a link button. Tables are not supported in MAX."""
    date_label = sheet["date_label"]
    header_lines = [
        f"**Замены на {date_label}**",
        f"{sheet['week']}-я неделя, {sheet['weekday_label']}",
    ]
    url = f"{origin}/changes/{sheet['id']}" if origin else ""
    if url:
        header_lines.append(f"[Открыть таблицу]({url})")
    header = "\n".join(header_lines)
    blocks = [_row_message(row) for row in sheet["rows"]]
    messages = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= _TEXT_LIMIT:
            current = candidate
            continue
        messages.append(current)
        current = f"**Замены на {date_label}, продолжение**\n\n{block}"
        if len(current) > _TEXT_LIMIT:
            current = current[: _TEXT_LIMIT - 1] + "…"
    if current:
        messages.append(current)
    if not messages:
        messages = [header]

    attachments = None
    if url.startswith("https://") and len(url) <= 2048:
        attachments = [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {
                                "type": "link",
                                "text": "Открыть таблицу",
                                "url": url,
                            }
                        ]
                    ]
                },
            }
        ]
    return messages, attachments


def _record_notify(sheet_id, error):
    db = get_db()
    if error:
        db.execute(
            """
            UPDATE substitution_sheets
            SET last_notify_error = ?
            WHERE id = ?
            """,
            (error[:300], sheet_id),
        )
    else:
        db.execute(
            """
            UPDATE substitution_sheets
            SET last_notify_at = ?, last_notify_error = ''
            WHERE id = ?
            """,
            (_now_stamp(), sheet_id),
        )
    db.commit()


def notify_sheet(sheet):
    """Post the sheet to the configured MAX chat. Publishing does not depend on this."""
    token = str(current_app.config.get("MAX_BOT_TOKEN") or "").strip()
    chat_id = _setting(get_db(), _NOTIFY_CHAT_KEY)
    origin = site_origin()
    if not token:
        message = "Бот MAX не настроен."
        _record_notify(sheet["id"], message)
        return {"sent": False, "error": message}
    if not chat_id:
        message = "Не указан чат MAX. Напишите боту /chatid и вставьте номер."
        _record_notify(sheet["id"], message)
        return {"sent": False, "error": message}

    messages, attachments = build_notice_messages(sheet, origin)
    client = MaxClient(
        token,
        current_app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
    )
    try:
        chat_target = int(chat_id)
    except ValueError:
        message = "ID чата для уведомлений указан неверно."
        _record_notify(sheet["id"], message)
        return {"sent": False, "error": message}

    try:
        for index, text in enumerate(messages):
            client.send_message(
                chat_id=chat_target,
                text=text,
                attachments=attachments if index == 0 else None,
                text_format="markdown",
            )
    except MaxApiError as exc:
        logger.error("MAX substitution notice failed: %s", exc.detail or exc)
        message = "MAX не принял сообщение. Проверьте, что бот есть в этом чате."
        _record_notify(sheet["id"], message)
        return {"sent": False, "error": message}
    except OSError:
        logger.exception("MAX substitution notice failed")
        message = "Не удалось связаться с MAX."
        _record_notify(sheet["id"], message)
        return {"sent": False, "error": message}

    warning = ""
    if not origin:
        warning = "Укажите адрес сайта в настройках MAX, чтобы в сообщении была ссылка."
    elif not origin.startswith("https://"):
        warning = "Ссылка на таблицу попадёт в текст. Кнопка в MAX работает только с адресом https://."
    _record_notify(sheet["id"], "")
    return {"sent": True, "warning": warning}


def resend_notice(sheet_id):
    sheet = get_sheet(sheet_id)
    if sheet is None:
        return None, "Лист замены не найден."
    if sheet["status"] != "published":
        return None, "Сначала опубликуйте лист."
    if not sheet["rows"]:
        return None, "В листе нет строк."
    return {"sheet": get_sheet(sheet_id), "notify": notify_sheet(sheet)}, None


def published_sheet(sheet_id):
    sheet = get_sheet(sheet_id)
    if sheet is None or sheet["status"] != "published":
        return None
    return sheet


def _group_matches(row, group_id, group_name):
    if row["group_id"] is not None and int(row["group_id"]) == int(group_id):
        return True
    return bool(group_name) and _norm_name(row["group_name"]) == _norm_name(group_name)


def _school_span(today):
    """Monday–Saturday that contains today. Sunday is between weeks."""
    if today.weekday() == 6:
        return None
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=5)


def _teacher_name_keys(full_name, short_name):
    keys = set()
    for value in (full_name, short_name):
        key = _norm_name(value)
        if key:
            keys.add(key)
    parts = str(full_name or "").split()
    if len(parts) >= 2:
        initials = "".join(part[0] for part in parts[1:] if part)
        if initials:
            keys.add(_norm_name(parts[0] + initials))
            keys.add(_norm_name(f"{parts[0]} {initials}"))
    return keys


def _collect_published(today, keep_row):
    """Nearest published sheet per week and weekday, with rows kept by keep_row."""
    today = today or school_today()
    horizon = today + timedelta(days=21)
    db = get_db()
    sheets = db.execute(
        """
        SELECT
            id, sheet_date, week, weekday, status,
            created_at, updated_at, published_at,
            last_notify_at, last_notify_error
        FROM substitution_sheets
        WHERE status = 'published' AND sheet_date >= ?
        ORDER BY sheet_date, id
        """,
        (today.isoformat(),),
    ).fetchall()
    grouped = {}
    for sheet in sheets:
        sheet_day = datetime.strptime(sheet["sheet_date"], "%Y-%m-%d").date()
        if sheet_day > horizon:
            continue
        rows = []
        for raw in _rows_for(db, sheet["id"]):
            item = _serialize_row(raw)
            if keep_row(item):
                rows.append(item)
        if not rows:
            continue
        payload = _serialize_sheet(sheet, [])
        payload["rows"] = rows
        payload["row_count"] = len(rows)
        payload["applies"] = True
        key = (int(sheet["week"]), int(sheet["weekday"]))
        grouped.setdefault(key, []).append((sheet_day, payload))
    current = []
    for items in grouped.values():
        nearest = min(day for day, _payload in items)
        current.extend(payload for day, payload in items if day == nearest)
    current.sort(key=lambda item: (item["sheet_date"], item["id"]))
    return current


def substitutions_for_group(group_id, group_name, today=None):
    """Published substitutions from today through the next three weeks.

    They replace the matching weekday in the timetable as soon as they are
    published, including tomorrow. The next calendar day they are gone and
    the ordinary lessons return. For one weekday only the nearest date is
    kept, so a later sheet does not cover today's pairs.
    """
    current = _collect_published(
        today,
        lambda row: _group_matches(row, group_id, group_name),
    )
    return {"current": current, "upcoming": []}


def substitutions_for_teacher(teacher_id, today=None):
    """Rows where this teacher substitutes or is the one being replaced."""
    db = get_db()
    teacher = db.execute(
        "SELECT id, full_name, short_name FROM teachers WHERE id = ?",
        (int(teacher_id),),
    ).fetchone()
    if teacher is None:
        return None
    keys = _teacher_name_keys(teacher["full_name"], teacher["short_name"])

    def keep(row):
        new_name = _norm_name(row["new_teacher"])
        absent_name = _norm_name(row["absent_teacher"])
        return new_name in keys or absent_name in keys

    current = _collect_published(today, keep)
    for sheet in current:
        for row in sheet["rows"]:
            row["for_new"] = _norm_name(row["new_teacher"]) in keys
            row["for_absent"] = _norm_name(row["absent_teacher"]) in keys
    return {
        "teacher": {
            "id": teacher["id"],
            "full_name": teacher["full_name"],
            "short_name": teacher["short_name"] or "",
        },
        "current": current,
    }
