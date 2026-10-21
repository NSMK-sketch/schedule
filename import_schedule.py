"""
Разовая загрузка расписания из Excel (только Лист1).

Пример:
  .venv\\Scripts\\python.exe import_schedule.py
  .venv\\Scripts\\python.exe import_schedule.py --file "расписание Первый-семестр-12-курс.xlsx"
  .venv\\Scripts\\python.exe import_schedule.py --file "расписание Первый-семестр-34-курс.xlsx" --keep-existing
  .venv\\Scripts\\python.exe import_schedule.py --dry-run

Сначала загрузите 1–2 курс (очистит БД), затем 3–4 курс с --keep-existing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from app import create_app
from app.database import get_db
from app.services.xlsx_reader import read_xlsx_rows


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_FILE = BASE_DIR / "расписание Первый-семестр-12-курс.xlsx"

DAY_NAMES = {
    "понедельник": 1,
    "вторник": 2,
    "среда": 3,
    "четверг": 4,
    "пятница": 5,
    "суббота": 6,
}

SKIP_SUBJECTS = {
    "классный час",
    "классныйчас",
}

TEACHER_COLORS = [
    "#3B82F6",
    "#22C55E",
    "#EAB308",
    "#A855F7",
    "#EF4444",
    "#0EA5E9",
    "#F97316",
    "#14B8A6",
    "#EC4899",
    "#6366F1",
]

WEEK_TOKEN_RE = re.compile(
    r"([12])\s*[НнHh]\s*[-–—:]?\s*",
    re.UNICODE,
)
PERIOD_RE = re.compile(r"^(\d)\s*пара$", re.IGNORECASE)
ROOM_WORD_RE = re.compile(
    r"(?i)\b(ауд\.?|кабинет|спортзал|тир|мастерск|библиот|геодез)",
)


def cell(rows: list[list], row_idx: int, col_idx: int) -> str:
    if row_idx < 0 or row_idx >= len(rows):
        return ""
    row = rows[row_idx]
    if col_idx < 0 or col_idx >= len(row):
        return ""
    value = row[col_idx]
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def clean_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def person_key(name: str) -> str:
    return re.sub(r"[\s.]+", "", name).casefold()


def short_name_from_full(full_name: str) -> str:
    parts = [part for part in re.split(r"\s+", full_name.strip()) if part]
    if not parts:
        return "ПРЕП"
    if len(parts) == 1:
        return parts[0][:4].upper()
    return "".join(part[0].upper() for part in parts)[:4]


def subject_short(name: str) -> str:
    compact = re.sub(r"\s+", " ", name).strip()
    if len(compact) <= 12:
        return compact
    return compact[:12].rstrip()


def guess_course(group_name: str) -> int:
    match = re.search(r"-(\d{2})-", group_name)
    if not match:
        return 1
    year = int(match.group(1))
    # Файл 2026 учебного года: набор 26 → 1 курс, 25 → 2 курс
    course = 26 - year + 1
    return course if course in range(1, 7) else 1


def guess_speciality(group_name: str) -> str:
    prefix = group_name.split("-", 1)[0].strip()
    return prefix


def strip_week_marker(text: str) -> str:
    return clean_spaces(WEEK_TOKEN_RE.sub("", text))


def split_week_variants(text: str) -> dict[int | None, str]:
    """Разбор ячейки с метками 1Н/2Н.

    Возвращает:
      {None: "текст"} — на обе недели;
      {1: "..."} / {2: "..."} / {1: "...", 2: "..."} — по неделям.
    """
    raw = clean_spaces(text)
    if not raw:
        return {}

    marks = list(WEEK_TOKEN_RE.finditer(raw))
    if not marks:
        return {None: raw}

    if len(marks) == 1:
        week = int(marks[0].group(1))
        body = strip_week_marker(raw)
        return {week: body} if body else {}

    parts: dict[int, str] = {}
    for index, mark in enumerate(marks):
        week = int(mark.group(1))
        start = mark.end()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(raw)
        chunk = raw[start:end].strip(" \t/-–—|")
        chunk = clean_spaces(chunk)
        if chunk:
            parts[week] = chunk
    return parts


def split_pair(text: str) -> tuple[str, str | None]:
    """Два преподавателя/аудитории через ; или / (без меток недели)."""
    raw = clean_spaces(text)
    if not raw:
        return "", None

    if ";" in raw:
        left, right = raw.split(";", 1)
        left, right = clean_spaces(left), clean_spaces(right)
        return left, right or None

    if "/" in raw:
        left, right = raw.split("/", 1)
        left, right = clean_spaces(left), clean_spaces(right)
        return left, right or None

    return raw, None


def normalize_room(text: str) -> str:
    value = clean_spaces(text)
    if not value:
        return ""
    value = re.sub(r"(?i)^ауд\.?\s*", "", value).strip()
    value = re.sub(r"(?i)^кабинет\.?\s*", "", value).strip()
    if not value:
        return ""
    # "49." / "306.0" из Excel
    try:
        number = float(value.replace(",", "."))
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return value


def looks_like_room(text: str) -> bool:
    if not text:
        return False
    if ROOM_WORD_RE.search(text):
        return True
    stripped = normalize_room(text)
    return bool(re.search(r"\d", stripped))


def should_skip_subject(name: str) -> bool:
    key = re.sub(r"\s+", "", name).casefold()
    return not name or key in SKIP_SUBJECTS


def find_groups(header_row: list) -> list[tuple[int, str]]:
    groups: list[tuple[int, str]] = []
    for col_idx, value in enumerate(header_row):
        if col_idx < 4:  # A-D служебные
            continue
        name = clean_spaces(str(value or ""))
        if not name or name.casefold() in {"дни недели", "время занятий"}:
            continue
        # колонки W/X — дубли подписей пар/дней
        if re.fullmatch(r"\d\s*пара", name, flags=re.I):
            continue
        if name.casefold() in DAY_NAMES:
            continue
        groups.append((col_idx, name))
    return groups


def detect_day(rows: list[list], row_idx: int) -> int | None:
    for col_idx in (1, 23, 0):  # B, X, A
        value = cell(rows, row_idx, col_idx).casefold()
        if value in DAY_NAMES:
            return DAY_NAMES[value]
    return None


def detect_period(rows: list[list], row_idx: int) -> int | None:
    for col_idx in (2, 22):  # C, W
        value = cell(rows, row_idx, col_idx)
        match = PERIOD_RE.match(value)
        if match:
            period = int(match.group(1))
            if period in range(1, 5):
                return period
    return None


def pick_for_week(variants: dict[int | None, str], week: int) -> str:
    if week in variants:
        return variants[week]
    if None in variants:
        return variants[None]
    return ""


def _variants_for_slot(
    raw: str, subject_weeks: list[int], *, prefer_week_split_on_slash: bool
) -> dict[int | None, str]:
    """Сопоставить текст преподавателя/аудитории с неделями предмета."""
    week_parts = split_week_variants(raw)
    if not raw.strip():
        return {}

    # Явные 1Н/2Н
    if week_parts and set(week_parts) != {None}:
        return week_parts

    text = week_parts.get(None, clean_spaces(raw))
    dual_subject = set(subject_weeks) == {1, 2}

    # Для аудиторий при предмете 1Н/2Н запись «39А / 38» = разные недели
    if (
        prefer_week_split_on_slash
        and dual_subject
        and ("/" in text or ";" in text)
    ):
        first, second = split_pair(text)
        if first and second:
            return {1: first, 2: second}

    return {None: text}


def resolve_people_for_week(
    teacher_raw: str, week: int, subject_weeks: list[int]
) -> tuple[str, str | None]:
    variants = _variants_for_slot(
        teacher_raw, subject_weeks, prefer_week_split_on_slash=False
    )
    text = pick_for_week(variants, week)
    if not text:
        return "", None
    # подгруппы: «А; Б» или «А/ Б» без меток недели
    if set(variants) == {None}:
        return split_pair(text)
    if ";" in text:
        left, right = text.split(";", 1)
        return clean_spaces(left), clean_spaces(right) or None
    return clean_spaces(text), None


def resolve_rooms_for_week(
    room_raw: str, week: int, subject_weeks: list[int]
) -> tuple[str, str | None]:
    variants = _variants_for_slot(
        room_raw, subject_weeks, prefer_week_split_on_slash=True
    )
    text = pick_for_week(variants, week)
    if not text:
        return "", None
    if set(variants) == {None}:
        first, second = split_pair(text)
        return (
            normalize_room(first),
            normalize_room(second) if second else None,
        )
    if ";" in text:
        left, right = text.split(";", 1)
        return normalize_room(left), normalize_room(right) or None
    return normalize_room(text), None


def parse_lessons(rows: list[list]) -> tuple[list[dict], list[str]]:
    if not rows:
        raise ValueError("Лист пуст.")

    groups = find_groups(rows[0])
    if not groups:
        raise ValueError("В первой строке не найдены названия групп (колонки E…).")

    lessons: list[dict] = []
    warnings: list[str] = []
    current_day: int | None = None

    for row_idx in range(1, len(rows)):
        day = detect_day(rows, row_idx)
        if day:
            current_day = day

        period = detect_period(rows, row_idx)
        if not period or current_day is None:
            continue

        subject_row = row_idx
        teacher_row = row_idx + 1
        room_row = row_idx + 2

        for col_idx, group_name in groups:
            subject_raw = cell(rows, subject_row, col_idx)
            if should_skip_subject(subject_raw):
                continue

            teacher_raw = cell(rows, teacher_row, col_idx)
            room_raw = cell(rows, room_row, col_idx)

            subject_variants = split_week_variants(subject_raw)
            if not subject_variants:
                continue

            weeks = (
                [1, 2]
                if list(subject_variants.keys()) == [None]
                else sorted(week for week in subject_variants if week in (1, 2))
            )

            for week in weeks:
                subject_name = pick_for_week(subject_variants, week)
                if should_skip_subject(subject_name):
                    continue

                teacher_name, teacher2_name = resolve_people_for_week(
                    teacher_raw, week, weeks
                )
                room_name, room2_name = resolve_rooms_for_week(
                    room_raw, week, weeks
                )

                if not teacher_name:
                    warnings.append(
                        f"{group_name}: {DAY_NAMES_REV(current_day)} "
                        f"{period} пара, {week}н — нет преподавателя "
                        f"(«{subject_name}»)"
                    )
                    continue

                # вторая аудитория без второго преподавателя — оставим одну
                if room2_name and not teacher2_name:
                    room2_name = None

                lessons.append(
                    {
                        "group_name": group_name,
                        "weekday": current_day,
                        "period": period,
                        "week": week,
                        "subject_name": subject_name,
                        "teacher_name": teacher_name,
                        "teacher2_name": teacher2_name,
                        "classroom_name": room_name or None,
                        "classroom2_name": room2_name,
                        "lesson_type": "Занятие",
                        "note": "",
                    }
                )

    return lessons, warnings


def DAY_NAMES_REV(day: int) -> str:
    for name, number in DAY_NAMES.items():
        if number == day:
            return name.capitalize()
    return str(day)


class Catalog:
    def __init__(self, db):
        self.db = db
        self.groups = {
            row["name"].casefold(): row["id"]
            for row in db.execute("SELECT id, name FROM groups_ref")
        }
        self.teachers = {
            person_key(row["full_name"]): row["id"]
            for row in db.execute("SELECT id, full_name FROM teachers")
        }
        self.subjects = {
            row["name"].casefold(): row["id"]
            for row in db.execute("SELECT id, name FROM subjects")
        }
        self.classrooms = {
            row["name"].casefold(): row["id"]
            for row in db.execute("SELECT id, name FROM classrooms")
        }
        self._teacher_color_index = 0
        self.created = {
            "groups": 0,
            "teachers": 0,
            "subjects": 0,
            "classrooms": 0,
            "links": 0,
            "lessons": 0,
        }

    def ensure_group(self, name: str) -> int:
        key = name.casefold()
        if key in self.groups:
            return self.groups[key]
        cursor = self.db.execute(
            "INSERT INTO groups_ref (name, speciality, course) VALUES (?, ?, ?)",
            (name, guess_speciality(name), guess_course(name)),
        )
        group_id = cursor.lastrowid
        self.groups[key] = group_id
        self.created["groups"] += 1
        return group_id

    def ensure_teacher(self, name: str) -> int:
        key = person_key(name)
        if key in self.teachers:
            return self.teachers[key]
        color = TEACHER_COLORS[self._teacher_color_index % len(TEACHER_COLORS)]
        self._teacher_color_index += 1
        cursor = self.db.execute(
            "INSERT INTO teachers (full_name, short_name, color) VALUES (?, ?, ?)",
            (clean_spaces(name), short_name_from_full(name), color),
        )
        teacher_id = cursor.lastrowid
        self.teachers[key] = teacher_id
        self.created["teachers"] += 1
        return teacher_id

    def ensure_subject(self, name: str) -> int:
        key = name.casefold()
        if key in self.subjects:
            return self.subjects[key]
        cursor = self.db.execute(
            "INSERT INTO subjects (name, short_name, color) VALUES (?, ?, ?)",
            (name, subject_short(name), "#6366f1"),
        )
        subject_id = cursor.lastrowid
        self.subjects[key] = subject_id
        self.created["subjects"] += 1
        return subject_id

    def ensure_classroom(self, name: str | None) -> int | None:
        if not name:
            return None
        key = name.casefold()
        if key in self.classrooms:
            return self.classrooms[key]
        room_type = ""
        if any(token in key for token in ("спорт", "тир", "мастер", "библио", "геодез")):
            room_type = name
        cursor = self.db.execute(
            "INSERT INTO classrooms (name, room_type, seats) VALUES (?, ?, NULL)",
            (name, room_type),
        )
        classroom_id = cursor.lastrowid
        self.classrooms[key] = classroom_id
        self.created["classrooms"] += 1
        return classroom_id

    def ensure_link(self, teacher_id: int, subject_id: int) -> None:
        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO teacher_subjects (teacher_id, subject_id)
            VALUES (?, ?)
            """,
            (teacher_id, subject_id),
        )
        if cursor.rowcount:
            self.created["links"] += 1


def wipe_schedule_data(db) -> None:
    db.execute("DELETE FROM lessons")
    db.execute("DELETE FROM teacher_subjects")
    db.execute("DELETE FROM groups_ref")
    db.execute("DELETE FROM teachers")
    db.execute("DELETE FROM subjects")
    db.execute("DELETE FROM classrooms")


def import_lessons(lessons: list[dict], *, replace: bool) -> Catalog:
    db = get_db()
    if replace:
        wipe_schedule_data(db)

    catalog = Catalog(db)
    seen_slots: set[tuple] = set()

    for item in lessons:
        slot = (
            item["group_name"].casefold(),
            item["week"],
            item["weekday"],
            item["period"],
        )
        if slot in seen_slots:
            continue
        seen_slots.add(slot)

        group_id = catalog.ensure_group(item["group_name"])
        subject_id = catalog.ensure_subject(item["subject_name"])
        teacher_id = catalog.ensure_teacher(item["teacher_name"])
        teacher2_id = (
            catalog.ensure_teacher(item["teacher2_name"])
            if item["teacher2_name"]
            else None
        )
        classroom_id = catalog.ensure_classroom(item["classroom_name"])
        classroom2_id = (
            catalog.ensure_classroom(item["classroom2_name"])
            if item["classroom2_name"] and teacher2_id
            else None
        )

        catalog.ensure_link(teacher_id, subject_id)
        if teacher2_id:
            catalog.ensure_link(teacher2_id, subject_id)

        db.execute(
            """
            INSERT INTO lessons (
                group_id, teacher_id, teacher2_id, subject_id,
                classroom_id, classroom2_id,
                weekday, period, week, lesson_type, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                group_id,
                teacher_id,
                teacher2_id,
                subject_id,
                classroom_id,
                classroom2_id,
                item["weekday"],
                item["period"],
                item["week"],
                item["lesson_type"],
                item["note"],
            ),
        )
        catalog.created["lessons"] += 1

    db.commit()
    return catalog


def default_schedule_file() -> Path:
    if DEFAULT_FILE.is_file():
        return DEFAULT_FILE
    matches = sorted(
        path
        for path in BASE_DIR.glob("*.xlsx")
        if not path.name.startswith("~$")
        and "семестр" in path.name.casefold()
    )
    if matches:
        return matches[0]
    return DEFAULT_FILE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Разовая загрузка расписания из Excel (Лист1)."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Путь к .xlsx (по умолчанию файл семестра в корне проекта)",
    )
    parser.add_argument(
        "--sheet",
        default="Лист1",
        help="Имя листа Excel (по умолчанию Лист1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только разобрать файл, без записи в БД",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Не очищать справочники и занятия перед импортом",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = args.file or default_schedule_file()
    if not path.is_file():
        print(f"Файл не найден: {path}", file=sys.stderr)
        return 1

    print(f"Файл: {path.name}")
    print(f"Лист: {args.sheet}")
    rows = read_xlsx_rows(path, sheet_name=args.sheet)
    lessons, warnings = parse_lessons(rows)

    groups = sorted({item["group_name"] for item in lessons})
    print(f"Групп в сетке: {len(groups)}")
    print(f"Занятий к загрузке: {len(lessons)}")
    if warnings:
        print(f"Предупреждений (без преподавателя): {len(warnings)}")
        for line in warnings[:15]:
            print(f"  ! {line}")
        if len(warnings) > 15:
            print(f"  … и ещё {len(warnings) - 15}")

    if args.dry_run:
        print("Dry-run: в БД ничего не записано.")
        # несколько примеров
        for item in lessons[:8]:
            print(
                f"  {item['group_name']} | {item['week']}н "
                f"д{item['weekday']} п{item['period']}: "
                f"{item['subject_name']} — {item['teacher_name']}"
                + (f" / {item['teacher2_name']}" if item["teacher2_name"] else "")
                + (f" @ {item['classroom_name']}" if item["classroom_name"] else "")
            )
        return 0

    app = create_app({"SEED_DEMO_DATA": False})
    with app.app_context():
        catalog = import_lessons(lessons, replace=not args.keep_existing)
        print("Готово:")
        for key, value in catalog.created.items():
            print(f"  {key}: {value}")
        total = get_db().execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        print(f"Всего занятий в БД: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
