import hashlib
import hmac
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from urllib.parse import quote

from werkzeug.security import generate_password_hash

from app import create_app
from app.services.max_bot import build_reply
from app.services.max_client import MaxClient
from app.services.max_init_data import validate_init_data


def _cleanup_db(path):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


def _insert_user(db_path, username, password, role):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), role),
        )
        connection.commit()
    finally:
        connection.close()


class ScheduleAppTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        os.remove(self.db_path)

        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.db_path,
                "SEED_DEMO_DATA": True,
                "SECRET_KEY": "test-secret",
            }
        )
        _insert_user(self.db_path, "admin", "admin", "admin")
        _insert_user(self.db_path, "teacher", "teacher", "teacher")
        self.client = self.app.test_client()

    def tearDown(self):
        _cleanup_db(self.db_path)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_login_page_has_no_demo_password(self):
        page = self.client.get("/admin").get_data(as_text=True)
        self.assertIn("login-form", page)
        self.assertNotIn("Демо-данные", page)
        self.assertNotIn(">admin</code>", page)

    def test_login_admin(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["role"], "admin")

    def test_teacher_cannot_create_lesson(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "teacher", "password": "teacher"},
        )
        response = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 1,
                "period": 1,
                "group_id": 1,
                "teacher_id": 1,
                "subject_id": 1,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_bootstrap_requires_auth(self):
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 401)

    def test_admin_can_update_group(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        response = self.client.put(
            "/api/groups/1",
            json={"name": "П-21", "speciality": "Программирование", "course": 3},
        )
        self.assertEqual(response.status_code, 200)

        bootstrap = self.client.get("/api/bootstrap").get_json()
        group = next(item for item in bootstrap["groups"] if item["id"] == 1)
        self.assertEqual(group["course"], 3)

    def test_lesson_update_not_hijacked_by_reference_route(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        lessons = self.client.get("/api/lessons?week=1").get_json()
        self.assertTrue(lessons)
        lesson = lessons[0]
        response = self.client.put(
            f"/api/lessons/{lesson['id']}",
            json={
                "week": lesson["week"],
                "weekday": lesson["weekday"],
                "period": lesson["period"],
                "group_id": lesson["group_id"],
                "teacher_id": lesson["teacher_id"],
                "subject_id": lesson["subject_id"],
                "classroom_id": lesson["classroom_id"],
                "lesson_type": lesson["lesson_type"],
                "note": "тест",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_group_cascades_lessons(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        before = self.client.get("/api/lessons").get_json()
        self.assertTrue(any(item["group_id"] == 1 for item in before))

        response = self.client.delete("/api/groups/1")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.get_json()["removed_lessons"], 1)

        after = self.client.get("/api/lessons").get_json()
        self.assertFalse(any(item["group_id"] == 1 for item in after))

    def test_create_lesson_without_subject(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        response = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 5,
                "period": 4,
                "group_id": 2,
                "teacher_id": 1,
                "subject_id": None,
                "lesson_type": "Лекция",
            },
        )
        self.assertEqual(response.status_code, 201)

        lessons = self.client.get("/api/lessons?week=1").get_json()
        created = next(item for item in lessons if item["id"] == response.get_json()["id"])
        self.assertIsNone(created["subject_id"])
        self.assertIsNone(created["subject_name"])

    def test_copy_week_overwrites_target(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        week1_before = self.client.get("/api/lessons?week=1").get_json()
        self.assertTrue(week1_before)

        response = self.client.post(
            "/api/lessons/copy-week",
            json={"source_week": 1, "target_week": 2},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["copied"], len(week1_before))
        self.assertIn("removed", payload)

        week2 = self.client.get("/api/lessons?week=2").get_json()
        self.assertEqual(len(week2), len(week1_before))

        # Second overwrite should replace previous copies
        again = self.client.post(
            "/api/lessons/copy-week",
            json={"source_week": 1, "target_week": 2},
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["removed"], len(week1_before))
        self.assertEqual(
            len(self.client.get("/api/lessons?week=2").get_json()),
            len(week1_before),
        )

    def test_delete_classroom_unlinks_lessons(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        response = self.client.delete("/api/classrooms/1")
        self.assertEqual(response.status_code, 200)

        lessons = self.client.get("/api/lessons").get_json()
        self.assertFalse(any(item["classroom_id"] == 1 for item in lessons))

    def test_clear_groups_removes_lessons(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        before = self.client.get("/api/bootstrap").get_json()
        self.assertTrue(before["groups"])

        response = self.client.delete("/api/groups/all")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["removed_items"], 0)

        after = self.client.get("/api/bootstrap").get_json()
        self.assertEqual(after["groups"], [])
        self.assertEqual(self.client.get("/api/lessons").get_json(), [])

    def test_import_groups_from_project_file(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        self.client.delete("/api/groups/all")

        response = self.client.post("/api/groups/import")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["created"], 0)

        groups = self.client.get("/api/bootstrap").get_json()["groups"]
        self.assertTrue(any(item["name"] == "ИСП-23-1" for item in groups))

    def test_import_teachers_from_project_file(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        self.client.delete("/api/teachers/all")

        response = self.client.post("/api/teachers/import")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["created"], 0)

        teachers = self.client.get("/api/bootstrap").get_json()["teachers"]
        self.assertTrue(
            any(item["full_name"] == "Астафьева Нина Александровна" for item in teachers)
        )

    def test_teacher_cannot_import(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "teacher", "password": "teacher"},
        )
        response = self.client.post("/api/groups/import")
        self.assertEqual(response.status_code, 403)

    def test_import_classrooms_from_project_file(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        self.client.delete("/api/classrooms/all")

        response = self.client.post("/api/classrooms/import")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreater(payload["created"], 0)

        classrooms = self.client.get("/api/bootstrap").get_json()["classrooms"]
        self.assertTrue(any(item["name"] == "110" for item in classrooms))
        room = next(item for item in classrooms if item["name"] == "110")
        self.assertIn("математик", (room["room_type"] or "").lower())

    def test_create_split_lesson(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        response = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 4,
                "group_id": 2,
                "teacher_id": 1,
                "teacher2_id": 4,
                "subject_id": 1,
                "classroom_id": 1,
                "classroom2_id": 2,
                "lesson_type": "Лабораторная",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_json())

        lessons = self.client.get("/api/lessons?week=1").get_json()
        created = next(
            item for item in lessons if item["id"] == response.get_json()["id"]
        )
        self.assertEqual(created["teacher_id"], 1)
        self.assertEqual(created["teacher2_id"], 4)
        self.assertEqual(created["classroom_id"], 1)
        self.assertEqual(created["classroom2_id"], 2)
        self.assertTrue(created["teacher2_name"])
        self.assertTrue(created["classroom2_name"])

    def test_split_lesson_rejects_same_teacher(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        response = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 3,
                "group_id": 2,
                "teacher_id": 1,
                "teacher2_id": 1,
                "subject_id": 1,
                "lesson_type": "Практика",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("разных", response.get_json()["error"].lower())

    def test_teacher2_conflict(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        # Teacher 4 already busy as primary in one slot
        first = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 2,
                "group_id": 2,
                "teacher_id": 4,
                "subject_id": 1,
                "lesson_type": "Лекция",
            },
        )
        self.assertEqual(first.status_code, 201, first.get_json())

        # Another group tries to use teacher 4 as subgroup teacher in same slot
        conflict = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 2,
                "group_id": 3,
                "teacher_id": 1,
                "teacher2_id": 4,
                "subject_id": 1,
                "lesson_type": "Лабораторная",
            },
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertTrue(conflict.get_json()["error"].startswith("Конфликт:"))

    def test_force_allows_teacher_conflict(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        first = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 3,
                "group_id": 2,
                "teacher_id": 1,
                "subject_id": 1,
                "lesson_type": "Лекция",
            },
        )
        self.assertEqual(first.status_code, 201, first.get_json())

        forced = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 3,
                "group_id": 3,
                "teacher_id": 1,
                "subject_id": 1,
                "lesson_type": "Практика",
                "force": True,
            },
        )
        self.assertEqual(forced.status_code, 201, forced.get_json())

    def test_copy_week_preserves_teacher2(self):
        self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        created = self.client.post(
            "/api/lessons",
            json={
                "week": 1,
                "weekday": 6,
                "period": 1,
                "group_id": 2,
                "teacher_id": 1,
                "teacher2_id": 4,
                "subject_id": 1,
                "classroom_id": 1,
                "classroom2_id": 3,
                "lesson_type": "Лабораторная",
            },
        )
        self.assertEqual(created.status_code, 201, created.get_json())

        response = self.client.post(
            "/api/lessons/copy-week",
            json={"source_week": 1, "target_week": 2},
        )
        self.assertEqual(response.status_code, 200)

        week2 = self.client.get("/api/lessons?week=2").get_json()
        match = next(
            item
            for item in week2
            if item["weekday"] == 6
            and item["period"] == 1
            and item["group_id"] == 2
        )
        self.assertEqual(match["teacher2_id"], 4)
        self.assertEqual(match["classroom2_id"], 3)


def _sign_init_data(token, pairs):
    launch = "\n".join(f"{key}={value}" for key, value in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret, launch.encode("utf-8"), hashlib.sha256).hexdigest()


def _init_data(token, pairs):
    signed = _sign_init_data(token, pairs)
    encoded = "&".join(f"{key}={quote(value, safe='')}" for key, value in pairs)
    return f"{encoded}&hash={signed}"


class MaxIntegrationTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        os.remove(self.db_path)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.db_path,
                "SEED_DEMO_DATA": True,
                "SECRET_KEY": "test-secret",
                "MAX_BOT_TOKEN": "test-token",
                "MAX_WEBHOOK_SECRET": "test-secret",
                "MAX_WEBHOOK_URL": "",
                "MAX_MINIAPP_URL": "https://example.com",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        _cleanup_db(self.db_path)

    def _pairs(self, auth_date=None, start_param="g_1"):
        if auth_date is None:
            auth_date = str(int(time.time()))
        return [
            ("auth_date", auth_date),
            ("query_id", "abc"),
            ("start_param", start_param),
            ("user", '{"id":7,"first_name":"Max"}'),
        ]

    def _cyrillic_pairs(self, auth_date=None, start_param="g_1"):
        if auth_date is None:
            auth_date = str(int(time.time()))
        user = (
            '{"id":7,"first_name":"Иван",'
            '"photo_url":"https://cdn.example/a%20b.jpg"}'
        )
        return [
            ("auth_date", auth_date),
            ("query_id", "abc"),
            ("start_param", start_param),
            ("user", user),
        ]

    def test_init_data_accepts_valid_signature(self):
        raw = _init_data("test-token", self._pairs())
        parsed = validate_init_data(raw, "test-token")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["start_param"], "g_1")
        self.assertIn("Max", parsed["user"])

    def test_init_data_accepts_cyrillic_user(self):
        raw = _init_data("test-token", self._cyrillic_pairs())
        with self.assertNoLogs("app.services.max_init_data", level="WARNING"):
            parsed = validate_init_data(raw, "test-token")
        self.assertEqual(parsed["start_param"], "g_1")
        self.assertIn("Иван", parsed["user"])
        self.assertIn("a%20b.jpg", parsed["user"])

    def test_init_data_accepts_web_app_data_fragment(self):
        raw = _init_data("test-token", self._cyrillic_pairs())
        encoded = quote(raw, safe="")
        official = f"https://web.max.ru/#WebAppData={encoded}&WebAppPlatform=web"
        partial = "WebAppData=" + raw.replace("&", "%26").replace("=", "%3D")
        for fragment in (official, partial):
            parsed = validate_init_data(fragment, "test-token")
            self.assertIsNotNone(parsed, fragment[:40])
            self.assertIn("Иван", parsed["user"])
            self.assertIn("a%20b.jpg", parsed["user"])

    def test_init_data_rejects_tampered_hash(self):
        raw = _init_data("test-token", self._cyrillic_pairs()) + "ff"
        with self.assertLogs("app.services.max_init_data", level="WARNING") as captured:
            self.assertIsNone(validate_init_data(raw, "test-token"))
        text = "\n".join(captured.output)
        self.assertIn("подпись не сошлась", text)
        self.assertNotIn("test-token", text)
        self.assertNotIn("Иван", text)
        self.assertNotIn("a%20b.jpg", text)
        self.assertNotIn(raw.split("hash=", 1)[1], text)

    def test_init_data_rejects_missing_hash(self):
        raw = _init_data("test-token", self._pairs()).split("&hash=", 1)[0]
        with self.assertLogs("app.services.max_init_data", level="WARNING") as captured:
            self.assertIsNone(validate_init_data(raw, "test-token"))
        self.assertIn("нет hash", "\n".join(captured.output))

    def test_init_data_rejects_duplicate_key(self):
        raw = "query_id=other&" + _init_data("test-token", self._pairs())
        with self.assertLogs("app.services.max_init_data", level="WARNING") as captured:
            self.assertIsNone(validate_init_data(raw, "test-token"))
        self.assertIn("повтор ключа", "\n".join(captured.output))

    def test_init_data_rejects_expired_auth_date(self):
        auth_date = int(time.time()) - 7200
        raw = _init_data("test-token", self._pairs(auth_date=str(auth_date)))
        fragment = "WebAppData=" + raw.replace("&", "%26").replace("=", "%3D")
        with self.assertLogs("app.services.max_init_data", level="WARNING") as captured:
            self.assertIsNone(validate_init_data(raw, "test-token", now=auth_date + 7200))
            self.assertIsNone(
                validate_init_data(fragment, "test-token", now=auth_date + 7200)
            )
        text = "\n".join(captured.output)
        self.assertIn("auth_date старше 3600 секунд", text)
        self.assertIn("age_seconds=7200", text)
        self.assertNotIn("test-token", text)

    def test_session_endpoint_accepts_signed_launch(self):
        raw = _init_data("test-token", self._pairs(start_param="g_12"))
        response = self.client.post("/api/public/max/session", json={"init_data": raw})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["start_param"], "g_12")

    def test_session_endpoint_rejects_bad_signature(self):
        response = self.client.post(
            "/api/public/max/session",
            json={"init_data": "auth_date=1&hash=deadbeef"},
        )
        self.assertEqual(response.status_code, 401)

    def test_webhook_rejects_missing_secret(self):
        response = self.client.post(
            "/max/webhook",
            json={"update_type": "dialog_muted"},
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_accepts_secret_without_calling_max(self):
        from app.routes import max_webhook

        def fail_init(*_args, **_kwargs):
            raise AssertionError("MAX client must not be created")

        original = max_webhook.MaxClient
        max_webhook.MaxClient = fail_init
        try:
            response = self.client.post(
                "/max/webhook",
                json={"update_type": "dialog_muted"},
                headers={"X-Max-Bot-Api-Secret": "test-secret"},
            )
        finally:
            max_webhook.MaxClient = original

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_build_reply_opens_miniapp(self):
        reply = build_reply(
            {
                "update_type": "bot_started",
                "chat_id": 5,
                "user": {"user_id": 9, "name": "Студент"},
            },
            "https://example.com",
            "nsmkraspi_bot",
            4242,
        )
        self.assertEqual(reply["user_id"], 9)
        button = reply["attachments"][0]["payload"]["buttons"][0][0]
        self.assertEqual(button["type"], "open_app")
        self.assertEqual(button["text"], "Открыть расписание")
        self.assertEqual(button["web_app"], "nsmkraspi_bot")
        self.assertEqual(button["contact_id"], 4242)

        linked = build_reply(
            {
                "update_type": "bot_started",
                "chat_id": 5,
                "user": {"user_id": 9},
            },
            "https://max.ru/nsmkraspi_bot",
            "other_bot",
        )
        self.assertEqual(
            linked["attachments"][0]["payload"]["buttons"][0][0]["web_app"],
            "https://max.ru/nsmkraspi_bot",
        )

        ignored = build_reply(
            {
                "update_type": "message_created",
                "message": {
                    "sender": {"user_id": 9},
                    "body": {"text": "привет"},
                },
            },
            "",
            "nsmkraspi_bot",
        )
        self.assertIsNone(ignored)

        asked = build_reply(
            {
                "update_type": "message_created",
                "message": {
                    "sender": {"user_id": 9},
                    "body": {"text": "/start"},
                },
            },
            "",
            "nsmkraspi_bot",
        )
        button = asked["attachments"][0]["payload"]["buttons"][0][0]
        self.assertEqual(button["web_app"], "nsmkraspi_bot")

    def test_max_bot_me_when_token_configured(self):
        from app.config import Config

        token = os.getenv("MAX_BOT_TOKEN", "").strip() or Config.MAX_BOT_TOKEN
        if not token or token == "test-token":
            self.skipTest("MAX_BOT_TOKEN is not set")
        me = MaxClient(token, Config.MAX_API_BASE).get_me()
        self.assertTrue(me.get("is_bot"))
        self.assertIn("user_id", me)


class SetupTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        os.remove(self.db_path)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.db_path,
                "SEED_DEMO_DATA": False,
                "SECRET_KEY": "test-secret",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        _cleanup_db(self.db_path)

    def test_fresh_database_has_no_demo_content(self):
        connection = sqlite3.connect(self.db_path)
        try:
            groups = connection.execute("SELECT COUNT(*) FROM groups_ref").fetchone()[0]
            users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(groups, 0)
        self.assertEqual(users, 0)

    def test_home_is_the_setup_page(self):
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("setup-form", page)
        self.assertNotIn("пароль <code>admin</code>", page)
        status = self.client.get("/api/setup/status")
        self.assertFalse(status.get_json()["installed"])

    def test_setup_creates_admin_and_then_locks(self):
        response = self.client.post(
            "/api/setup",
            json={
                "username": "director",
                "password": "correct-horse",
                "password_confirm": "correct-horse",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        me = self.client.get("/api/auth/me").get_json()
        self.assertTrue(me["authenticated"])
        self.assertEqual(me["username"], "director")
        self.assertEqual(me["role"], "admin")

        again = self.client.post(
            "/api/setup",
            json={
                "username": "other",
                "password": "correct-horse",
                "password_confirm": "correct-horse",
            },
        )
        self.assertEqual(again.status_code, 409)
        page = self.client.get("/admin").get_data(as_text=True)
        self.assertNotIn("setup-form", page)

    def test_setup_rejects_a_short_or_mismatched_password(self):
        short = self.client.post(
            "/api/setup",
            json={
                "username": "director",
                "password": "short",
                "password_confirm": "short",
            },
        )
        self.assertEqual(short.status_code, 400)
        mismatch = self.client.post(
            "/api/setup",
            json={
                "username": "director",
                "password": "correct-horse",
                "password_confirm": "other-horse",
            },
        )
        self.assertEqual(mismatch.status_code, 400)
        self.assertFalse(self.client.get("/api/setup/status").get_json()["installed"])

    def test_known_default_accounts_are_removed(self):
        _insert_user(self.db_path, "admin", "admin", "admin")
        _insert_user(self.db_path, "teacher", "teacher", "teacher")
        _insert_user(self.db_path, "registrar", "registrar-pass", "admin")
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "INSERT INTO lessons (group_id, teacher_id, weekday, period, week) "
            "VALUES (1, 1, 1, 1, 1)"
        )
        connection.commit()
        lessons_before = connection.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        connection.close()

        app = create_app(
            {
                "TESTING": True,
                "DATABASE": self.db_path,
                "SEED_DEMO_DATA": False,
                "SECRET_KEY": "test-secret",
            }
        )
        client = app.test_client()
        self.assertEqual(
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin"},
            ).status_code,
            401,
        )
        self.assertEqual(
            client.post(
                "/api/auth/login",
                json={"username": "teacher", "password": "teacher"},
            ).status_code,
            401,
        )
        kept = client.post(
            "/api/auth/login",
            json={"username": "registrar", "password": "registrar-pass"},
        )
        self.assertEqual(kept.status_code, 200)

        connection = sqlite3.connect(self.db_path)
        lessons_after = connection.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]
        connection.close()
        self.assertEqual(lessons_after, lessons_before)

    def test_secret_key_is_created_beside_the_database(self):
        directory = tempfile.mkdtemp()
        db_path = os.path.join(directory, "schedule.db")
        try:
            first = create_app(
                {
                    "TESTING": True,
                    "DATABASE": db_path,
                    "SECRET_KEY": "",
                    "SEED_DEMO_DATA": False,
                }
            )
            key = first.config["SECRET_KEY"]
            self.assertGreaterEqual(len(key), 32)
            self.assertNotEqual(key, "dev-secret-change-me")
            second = create_app(
                {
                    "TESTING": True,
                    "DATABASE": db_path,
                    "SECRET_KEY": "",
                    "SEED_DEMO_DATA": False,
                }
            )
            self.assertEqual(second.config["SECRET_KEY"], key)
            self.assertTrue(os.path.isfile(os.path.join(directory, "secret_key")))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
