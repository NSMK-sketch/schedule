import os
import sqlite3

from werkzeug.security import check_password_hash
from flask import current_app, g


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'teacher'
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS groups_ref (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    speciality TEXT NOT NULL DEFAULT '',
    course INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#4f46e5'
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    short_name TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#6366f1'
);

CREATE TABLE IF NOT EXISTS classrooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    room_type TEXT NOT NULL DEFAULT '',
    seats INTEGER
);

CREATE TABLE IF NOT EXISTS teacher_subjects (
    teacher_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,
    PRIMARY KEY (teacher_id, subject_id),
    FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    teacher2_id INTEGER,
    subject_id INTEGER,
    classroom_id INTEGER,
    classroom2_id INTEGER,
    weekday INTEGER NOT NULL,
    period INTEGER NOT NULL,
    week INTEGER NOT NULL DEFAULT 1,
    lesson_type TEXT NOT NULL DEFAULT 'Лекция',
    note TEXT DEFAULT '',
    FOREIGN KEY (group_id) REFERENCES groups_ref(id),
    FOREIGN KEY (teacher_id) REFERENCES teachers(id),
    FOREIGN KEY (teacher2_id) REFERENCES teachers(id),
    FOREIGN KEY (subject_id) REFERENCES subjects(id),
    FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
    FOREIGN KEY (classroom2_id) REFERENCES classrooms(id)
);

CREATE INDEX IF NOT EXISTS idx_lessons_week_day_period
    ON lessons (week, weekday, period);
CREATE INDEX IF NOT EXISTS idx_lessons_teacher
    ON lessons (teacher_id, week, weekday, period);
CREATE INDEX IF NOT EXISTS idx_lessons_group
    ON lessons (group_id, week, weekday, period);
CREATE INDEX IF NOT EXISTS idx_lessons_classroom
    ON lessons (classroom_id, week, weekday, period);
"""
# teacher2/classroom2 indexes are created in _migrate_schema after columns exist



def _columns(db, table_name):
    return {
        row[1]
        for row in db.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _ensure_column(db, table_name, column_name, definition):
    if column_name not in _columns(db, table_name):
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _migrate_schema(db):
    columns = _columns(db, "users")
    if columns:
        if "password_hash" not in columns and "password" in columns:
            db.execute("ALTER TABLE users RENAME TO users_old")
            db.execute(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'teacher'
                )
                """
            )
            old_columns = _columns(db, "users_old")
            role_expression = "role" if "role" in old_columns else "'teacher'"
            db.execute(
                f"""
                INSERT INTO users (id, username, password_hash, role)
                SELECT id, username, password, {role_expression}
                FROM users_old
                """
            )
            db.execute("DROP TABLE users_old")

    lesson_columns = _columns(db, "lessons")
    if lesson_columns and "weekday" not in lesson_columns and "day" in lesson_columns:
        db.execute("ALTER TABLE lessons RENAME TO lessons_old")
        db.execute(
            """
            CREATE TABLE lessons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                classroom_id INTEGER,
                weekday INTEGER NOT NULL,
                period INTEGER NOT NULL,
                week INTEGER NOT NULL DEFAULT 1,
                lesson_type TEXT NOT NULL DEFAULT 'Лекция',
                note TEXT DEFAULT '',
                FOREIGN KEY (group_id) REFERENCES groups_ref(id),
                FOREIGN KEY (teacher_id) REFERENCES teachers(id),
                FOREIGN KEY (subject_id) REFERENCES subjects(id),
                FOREIGN KEY (classroom_id) REFERENCES classrooms(id)
            )
            """
        )
        old_columns = _columns(db, "lessons_old")
        note_column = "notes" if "notes" in old_columns else "''"
        lesson_type_column = (
            "lesson_type" if "lesson_type" in old_columns else "'Лекция'"
        )
        db.execute(
            f"""
            INSERT INTO lessons (
                id, group_id, teacher_id, subject_id, classroom_id,
                weekday, period, week, lesson_type, note
            )
            SELECT
                id, group_id, teacher_id, subject_id, classroom_id,
                day, pair_number, week, {lesson_type_column}, {note_column}
            FROM lessons_old
            """
        )
        db.execute("DROP TABLE lessons_old")

    if _columns(db, "groups_ref"):
        _ensure_column(db, "groups_ref", "speciality", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "groups_ref", "course", "INTEGER NOT NULL DEFAULT 1")

    if _columns(db, "subjects"):
        _ensure_column(db, "subjects", "short_name", "TEXT NOT NULL DEFAULT ''")

    if _columns(db, "classrooms"):
        _ensure_column(db, "classrooms", "room_type", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "classrooms", "seats", "INTEGER")

    _migrate_nullable_subject(db)

    if _columns(db, "lessons"):
        _ensure_column(db, "lessons", "teacher2_id", "INTEGER")
        _ensure_column(db, "lessons", "classroom2_id", "INTEGER")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lessons_teacher2 "
            "ON lessons (teacher2_id, week, weekday, period)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lessons_classroom2 "
            "ON lessons (classroom2_id, week, weekday, period)"
        )


def _migrate_nullable_subject(db):
    """Allow lessons without a subject (placeholder until discipline is chosen)."""
    rows = db.execute("PRAGMA table_info(lessons)").fetchall()
    if not rows:
        return

    subject_col = next((row for row in rows if row[1] == "subject_id"), None)
    if subject_col is None:
        return

    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    if not subject_col[3]:
        return

    db.execute("ALTER TABLE lessons RENAME TO lessons_old")
    db.execute(
        """
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            teacher_id INTEGER NOT NULL,
            subject_id INTEGER,
            classroom_id INTEGER,
            weekday INTEGER NOT NULL,
            period INTEGER NOT NULL,
            week INTEGER NOT NULL DEFAULT 1,
            lesson_type TEXT NOT NULL DEFAULT 'Лекция',
            note TEXT DEFAULT '',
            FOREIGN KEY (group_id) REFERENCES groups_ref(id),
            FOREIGN KEY (teacher_id) REFERENCES teachers(id),
            FOREIGN KEY (subject_id) REFERENCES subjects(id),
            FOREIGN KEY (classroom_id) REFERENCES classrooms(id)
        )
        """
    )
    db.execute(
        """
        INSERT INTO lessons (
            id, group_id, teacher_id, subject_id, classroom_id,
            weekday, period, week, lesson_type, note
        )
        SELECT
            id, group_id, teacher_id, subject_id, classroom_id,
            weekday, period, week, lesson_type, note
        FROM lessons_old
        """
    )
    db.execute("DROP TABLE lessons_old")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_lessons_week_day_period "
        "ON lessons (week, weekday, period)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_lessons_teacher "
        "ON lessons (teacher_id, week, weekday, period)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_lessons_group "
        "ON lessons (group_id, week, weekday, period)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_lessons_classroom "
        "ON lessons (classroom_id, week, weekday, period)"
    )


def _seed_demo_data(db):
    """Fill reference data once so the board is useful out of the box."""
    group_count = db.execute("SELECT COUNT(*) FROM groups_ref").fetchone()[0]
    if group_count:
        return

    groups = [
        ("П-21", "Программирование", 2),
        ("П-22", "Программирование", 2),
        ("П-23", "Программирование", 2),
        ("ИС-21", "Информационные системы", 2),
    ]
    db.executemany(
        "INSERT INTO groups_ref (name, speciality, course) VALUES (?, ?, ?)",
        groups,
    )

    teachers = [
        ("Иванов Сергей Владимирович", "ИСВ", "#3B82F6"),
        ("Петрова Анна Ивановна", "ПАИ", "#22C55E"),
        ("Сидоров Дмитрий Алексеевич", "СДА", "#EAB308"),
        ("Морозова Елена Викторовна", "МЕВ", "#A855F7"),
    ]
    db.executemany(
        "INSERT INTO teachers (full_name, short_name, color) VALUES (?, ?, ?)",
        teachers,
    )

    subjects = [
        ("Информатика", "ИНФ", "#3B82F6"),
        ("Основы алгоритмизации и программирования", "ОАП", "#6366f1"),
        ("Программирование", "ПРОГ", "#0ea5e9"),
        ("Математика", "МАТ", "#22C55E"),
        ("Физика", "ФИЗ", "#EAB308"),
        ("Базы данных", "БД", "#A855F7"),
    ]
    db.executemany(
        "INSERT INTO subjects (name, short_name, color) VALUES (?, ?, ?)",
        subjects,
    )

    classrooms = [
        ("305", "лаборатория", 25),
        ("204", "лекционная", 30),
        ("312", "лаборатория", 20),
    ]
    db.executemany(
        "INSERT INTO classrooms (name, room_type, seats) VALUES (?, ?, ?)",
        classrooms,
    )

    links = [
        (1, 1), (1, 2), (1, 3),
        (2, 4), (2, 5),
        (3, 3), (3, 6),
        (4, 1), (4, 6),
    ]
    db.executemany(
        "INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (?, ?)",
        links,
    )

    lessons = [
        # week, weekday, period, group, teacher, subject, classroom, type
        (1, 1, 1, 1, 1, 1, 1, "Лекция"),
        (1, 1, 2, 1, 2, 4, 2, "Практика"),
        (1, 2, 1, 3, 4, 6, 1, "Лекция"),
        (2, 1, 1, 2, 3, 3, 3, "Лабораторная"),
        (2, 1, 3, 1, 1, 2, 1, "Практика"),
        (2, 3, 2, 4, 2, 5, 2, "Лекция"),
    ]
    db.executemany(
        """
        INSERT INTO lessons (
            week, weekday, period, group_id, teacher_id, subject_id,
            classroom_id, lesson_type, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
        """,
        lessons,
    )


# Removed on startup. These passwords were shipped with the app.
_DEFAULT_CREDENTIALS = (
    ("admin", "admin"),
    ("teacher", "teacher"),
)


def remove_default_credentials(db):
    removed = 0
    rows = db.execute("SELECT id, username, password_hash FROM users").fetchall()
    for user_id, username, password_hash in rows:
        for known_user, known_password in _DEFAULT_CREDENTIALS:
            if username != known_user:
                continue
            if check_password_hash(password_hash, known_password):
                db.execute("DELETE FROM users WHERE id = ?", (user_id,))
                removed += 1
            break
    return removed


def remove_default_credentials_from_path(path):
    db = sqlite3.connect(path)
    try:
        removed = remove_default_credentials(db)
        db.commit()
        return removed
    finally:
        db.close()


def init_db(app):
    database_dir = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(database_dir, exist_ok=True)

    db = sqlite3.connect(app.config["DATABASE"])
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA journal_mode = WAL").fetchone()
        db.executescript(SCHEMA)
        _migrate_schema(db)
        removed = remove_default_credentials(db)
        if removed:
            app.logger.warning(
                "Removed %s account(s) that still had the built-in passwords",
                removed,
            )

        if app.config.get("SEED_DEMO_DATA"):
            _seed_demo_data(db)

        db.commit()
    finally:
        db.close()

    app.teardown_appcontext(close_db)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=5)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
