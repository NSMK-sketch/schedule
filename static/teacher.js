const DAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
];

const BELL = {
    regular: [
        "09:00–09:45 / 09:50–10:35",
        "10:45–11:30 / 11:35–12:20",
        "13:05–13:50 / 13:55–14:40",
        "14:50–15:35 / 15:40–16:25",
    ],
    monday: [
        "10:00–10:45 / 10:50–11:35",
        "11:45–12:30 / 12:35–13:20",
        "14:05–14:50 / 14:55–15:40",
        "15:50–16:35 / 16:40–17:25",
    ],
};

const STORAGE_KEY = "nsmk_teacher_id";

const state = {
    teachers: [],
    teacherId: "",
    week: 1,
    lessons: [],
    teacher: null,
    substitutions: [],
};

const $ = (selector) => document.querySelector(selector);

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) =>
        ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#039;",
        })[char],
    );
}

function bellTime(weekday, period) {
    const list = weekday === 1 ? BELL.monday : BELL.regular;
    return list[period - 1] || "";
}

async function api(url) {
    const response = await fetch(url, { credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || "Не удалось загрузить данные.");
    }
    return data;
}

function readTeacherFromUrl() {
    const params = new URLSearchParams(window.location.search);
    return params.get("teacher") || params.get("teacher_id") || "";
}

function writeTeacherToUrl(teacherId) {
    const url = new URL(window.location.href);
    if (teacherId) {
        url.searchParams.set("teacher", teacherId);
    } else {
        url.searchParams.delete("teacher");
        url.searchParams.delete("teacher_id");
    }
    window.history.replaceState({}, "", url);
}

function fillTeachers() {
    const select = $("#teacher-select");
    const previous = String(state.teacherId || "");
    select.innerHTML = '<option value="">Выберите преподавателя…</option>';
    state.teachers
        .slice()
        .sort((a, b) => String(a.full_name).localeCompare(String(b.full_name), "ru"))
        .forEach((teacher) => {
            const option = document.createElement("option");
            option.value = String(teacher.id);
            option.textContent = teacher.full_name;
            select.append(option);
        });
    const exists = state.teachers.some((teacher) => String(teacher.id) === previous);
    select.value = exists ? previous : "";
    if (!exists) {
        state.teacherId = "";
    }
}

function renderMeta() {
    const node = $("#teacher-meta");
    if (!state.teacher) {
        node.classList.add("hidden");
        node.innerHTML = "";
        return;
    }
    node.classList.remove("hidden");
    node.innerHTML = `
        <strong>${esc(state.teacher.full_name)}</strong>
        <span>${esc(`${state.week}-я неделя`)}</span>
    `;
}

function lessonWord(count) {
    const n = count % 100;
    const n1 = count % 10;
    if (n > 10 && n < 20) {
        return "занятий";
    }
    if (n1 === 1) {
        return "занятие";
    }
    if (n1 > 1 && n1 < 5) {
        return "занятия";
    }
    return "занятий";
}

function sheetsForDay(day) {
    return (state.substitutions || []).filter(
        (sheet) => Number(sheet.week) === Number(state.week) && Number(sheet.weekday) === day,
    );
}

function slotKey(groupId, groupName, period) {
    if (groupId) {
        return `id:${groupId}|${period}`;
    }
    return `name:${String(groupName || "").trim().toLocaleLowerCase("ru")}|${period}`;
}

function coveredSlots(day) {
    const covered = new Set();
    sheetsForDay(day).forEach((sheet) => {
        (sheet.rows || []).forEach((row) => {
            (row.periods || []).forEach((period) => {
                covered.add(slotKey(row.group_id, row.group_name, Number(period)));
            });
        });
    });
    return covered;
}

function lessonCard(day, lesson) {
    const rooms = [lesson.classroom_name || null].filter(Boolean);
    const color = lesson.subject_color || "#a01914";
    const group = lesson.group_name || "Группа не указана";
    return `
        <article class="lesson-row">
            <div class="lesson-period">
                <b>${esc(lesson.period)}</b>
                <small>${esc(bellTime(day, Number(lesson.period)))}</small>
            </div>
            <div class="lesson-body" style="--lesson-color:${esc(color)}">
                <div class="lesson-subject">${esc(lesson.subject_name || "Предмет не назначен")}</div>
                <div class="lesson-teacher">${esc(group)}</div>
                ${
                    rooms.length
                        ? `<div class="lesson-meta"><span class="chip chip-room">ауд. ${esc(rooms.join(" / "))}</span></div>`
                        : ""
                }
            </div>
        </article>
    `;
}

function changeCard(day, row) {
    const periods = (row.periods || []).map(Number).filter((period) => period > 0);
    const label = periods.join(",") || row.periods_label || "";
    const times = periods.map((period) => bellTime(day, period)).filter(Boolean);
    const subject = row.cancelled ? "Занятие снято" : row.new_subject || "Предмет не указан";
    const group = row.group_name || "Группа не указана";
    return `
        <article class="lesson-row is-change">
            <div class="lesson-period">
                <b>${esc(label)}</b>
                <small>${esc(times.join(" / "))}</small>
            </div>
            <div class="lesson-body" style="--lesson-color:#a01914">
                <div class="lesson-flags">
                    <span class="change-badge${row.cancelled ? " is-off" : ""}">${row.cancelled ? "Снято" : "Замена"}</span>
                </div>
                <div class="lesson-subject">${esc(subject)}</div>
                <div class="lesson-teacher">${esc(group)}</div>
                ${
                    row.new_room
                        ? `<div class="lesson-meta"><span class="chip chip-room">ауд. ${esc(row.new_room)}</span></div>`
                        : ""
                }
                ${
                    row.old_subject
                        ? `<div class="lesson-instead">вместо: ${esc(row.old_subject)}</div>`
                        : ""
                }
            </div>
        </article>
    `;
}

function renderSchedule() {
    const root = $("#schedule-root");
    if (!state.teacherId) {
        root.innerHTML = `
            <div class="empty-state">
                <p>Выберите преподавателя — расписание откроется ниже.</p>
            </div>
        `;
        return;
    }

    const hasLessons = state.lessons.length > 0;
    const hasCurrent = (state.substitutions || []).some(
        (sheet) => Number(sheet.week) === Number(state.week),
    );
    if (!hasLessons && !hasCurrent) {
        root.innerHTML = `
            <div class="empty-state">
                <p>На эту неделю занятий нет.</p>
            </div>
        `;
        return;
    }

    const byDay = new Map();
    for (let day = 1; day <= 6; day += 1) {
        byDay.set(day, []);
    }
    state.lessons.forEach((lesson) => {
        const day = Number(lesson.weekday);
        if (byDay.has(day)) {
            byDay.get(day).push(lesson);
        }
    });

    const parts = [];
    for (let day = 1; day <= 6; day += 1) {
        const lessons = byDay
            .get(day)
            .slice()
            .sort((a, b) => Number(a.period) - Number(b.period) || String(a.group_name).localeCompare(String(b.group_name), "ru"));
        const covered = coveredSlots(day);
        const items = [];
        lessons.forEach((lesson) => {
            const period = Number(lesson.period);
            if (covered.has(slotKey(lesson.group_id, lesson.group_name, period))) {
                return;
            }
            items.push({
                period,
                html: lessonCard(day, lesson),
            });
        });
        sheetsForDay(day).forEach((sheet) => {
            (sheet.rows || []).forEach((row) => {
                if (!row.for_new) {
                    return;
                }
                const periods = (row.periods || []).map(Number);
                items.push({
                    period: periods.length ? Math.min(...periods) : 99,
                    html: changeCard(day, row),
                });
            });
        });
        if (!items.length) {
            continue;
        }
        items.sort((a, b) => a.period - b.period);

        parts.push(`
            <section class="day-block">
                <header class="day-head">
                    <b>${esc(DAYS[day - 1])}</b>
                    <span>${items.length} ${lessonWord(items.length)}</span>
                </header>
                <div class="day-lessons">${items.map((item) => item.html).join("")}</div>
            </section>
        `);
    }

    const empty = `<div class="empty-state"><p>На эту неделю занятий нет.</p></div>`;
    root.innerHTML = parts.length ? parts.join("") : empty;
}

async function loadSchedule() {
    const root = $("#schedule-root");
    if (!state.teacherId) {
        state.teacher = null;
        state.lessons = [];
        state.substitutions = [];
        renderMeta();
        renderSchedule();
        return;
    }

    root.innerHTML = `<div class="loading-state">Загрузка расписания…</div>`;
    try {
        const data = await api(
            `/api/public/teacher-schedule?teacher_id=${encodeURIComponent(state.teacherId)}&week=${state.week}`,
        );
        state.teacher = data.teacher;
        state.lessons = data.lessons || [];
        state.substitutions = data.substitutions || [];
        renderMeta();
        renderSchedule();
        document.title = `Расписание ${data.teacher.full_name} — НСМК`;
    } catch (error) {
        state.teacher = null;
        state.lessons = [];
        state.substitutions = [];
        renderMeta();
        root.innerHTML = `<div class="error-state">${esc(error.message)}</div>`;
    }
}

function setWeek(week) {
    state.week = week;
    document.querySelectorAll(".week-btn").forEach((button) => {
        button.classList.toggle("active", Number(button.dataset.week) === week);
    });
    loadSchedule();
}

function setTeacher(teacherId) {
    state.teacherId = teacherId ? String(teacherId) : "";
    if (state.teacherId) {
        localStorage.setItem(STORAGE_KEY, state.teacherId);
    } else {
        localStorage.removeItem(STORAGE_KEY);
    }
    writeTeacherToUrl(state.teacherId);
    $("#teacher-select").value = state.teacherId;
    loadSchedule();
}

async function init() {
    const fromUrl = readTeacherFromUrl();
    const fromStorage = localStorage.getItem(STORAGE_KEY) || "";
    try {
        state.teachers = await api("/api/public/teachers");
    } catch (error) {
        $("#schedule-root").innerHTML = `<div class="error-state">${esc(error.message)}</div>`;
        return;
    }

    state.teacherId = fromUrl || fromStorage || "";
    fillTeachers();
    $("#teacher-select").addEventListener("change", (event) => {
        setTeacher(event.target.value);
    });
    document.querySelectorAll(".week-btn").forEach((button) => {
        button.addEventListener("click", () => {
            setWeek(Number(button.dataset.week));
        });
    });

    if (state.teacherId) {
        $("#teacher-select").value = state.teacherId;
        writeTeacherToUrl(state.teacherId);
        await loadSchedule();
    } else {
        renderSchedule();
    }
}

init();
