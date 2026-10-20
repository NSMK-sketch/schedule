import os
import tempfile
import unittest

from app import create_app


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
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

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


if __name__ == "__main__":
    unittest.main()
