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

const STORAGE_KEY = "nsmk_student_group_id";

const state = {
    groups: [],
    groupId: "",
    week: 1,
    lessons: [],
    group: null,
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

function formatTeacher(fullName, shortName) {
    const parts = String(fullName || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean);
    if (!parts.length) {
        return shortName || "";
    }
    const surname = parts[0];
    const initials = parts
        .slice(1)
        .map((part) => `${part[0].toUpperCase()}.`)
        .join("");
    return initials ? `${surname} ${initials}` : surname;
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

function readGroupFromUrl() {
    const params = new URLSearchParams(window.location.search);
    return params.get("group") || params.get("group_id") || "";
}

function writeGroupToUrl(groupId) {
    const url = new URL(window.location.href);
    if (groupId) {
        url.searchParams.set("group", groupId);
    } else {
        url.searchParams.delete("group");
        url.searchParams.delete("group_id");
    }
    window.history.replaceState({}, "", url);
}

function fillGroups() {
    const select = $("#group-select");
    const previous = String(state.groupId || "");
    select.innerHTML = '<option value="">Выберите группу…</option>';

    const byCourse = new Map();
    state.groups.forEach((group) => {
        const course = Number(group.course) || 1;
        if (!byCourse.has(course)) {
            byCourse.set(course, []);
        }
        byCourse.get(course).push(group);
    });

    [...byCourse.keys()]
        .sort((a, b) => a - b)
        .forEach((course) => {
            const optgroup = document.createElement("optgroup");
            optgroup.label = `${course} курс`;
            byCourse
                .get(course)
                .sort((a, b) => String(a.name).localeCompare(String(b.name), "ru"))
                .forEach((group) => {
                    const option = document.createElement("option");
                    option.value = String(group.id);
                    option.textContent = group.name;
                    optgroup.append(option);
                });
            select.append(optgroup);
        });

    const exists = state.groups.some((group) => String(group.id) === previous);
    select.value = exists ? previous : "";
    if (!exists) {
        state.groupId = "";
    }
}

function renderMeta() {
    const node = $("#group-meta");
    if (!state.group) {
        node.classList.add("hidden");
        node.innerHTML = "";
        return;
    }

    const bits = [
        state.group.speciality || null,
        state.group.course ? `${state.group.course} курс` : null,
        `${state.week}-я неделя`,
    ].filter(Boolean);

    node.classList.remove("hidden");
    node.innerHTML = `
        <strong>${esc(state.group.name)}</strong>
        <span>${esc(bits.join(" · "))}</span>
    `;
}

function renderSchedule() {
    const root = $("#schedule-root");
    if (!state.groupId) {
        root.innerHTML = `
            <div class="empty-state">
                <p>Выберите свою группу — расписание откроется ниже.</p>
            </div>
        `;
        return;
    }

    if (!state.lessons.length) {
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
            .sort((a, b) => Number(a.period) - Number(b.period));
        if (!lessons.length) {
            continue;
        }

        const rows = lessons
            .map((lesson) => {
                const teacher1 = formatTeacher(
                    lesson.teacher_name,
                    lesson.teacher_short,
                );
                const teacher2 = lesson.teacher2_name
                    ? formatTeacher(lesson.teacher2_name, lesson.teacher2_short)
                    : "";
                const teacher = teacher2 ? `${teacher1} / ${teacher2}` : teacher1;
                const rooms = [
                    lesson.classroom_name || null,
                    lesson.classroom2_name || null,
                ].filter(Boolean);
                const color = lesson.subject_color || "#1f7aef";

                return `
                    <article class="lesson-row">
                        <div class="lesson-period">
                            <b>${esc(lesson.period)}</b>
                            <small>${esc(bellTime(day, Number(lesson.period)))}</small>
                        </div>
                        <div class="lesson-body" style="--lesson-color:${esc(color)}">
                            <div class="lesson-subject">${esc(lesson.subject_name || "Предмет не назначен")}</div>
                            <div class="lesson-teacher">${esc(teacher)}</div>
                            <div class="lesson-meta">
                                ${
                                    rooms.length
                                        ? `<span class="chip chip-room">ауд. ${esc(rooms.join(" / "))}</span>`
                                        : ""
                                }
                                ${
                                    lesson.lesson_type
                                        ? `<span class="chip">${esc(lesson.lesson_type)}</span>`
                                        : ""
                                }
                            </div>
                        </div>
                    </article>
                `;
            })
            .join("");

        parts.push(`
            <section class="day-block">
                <header class="day-head">
                    <b>${esc(DAYS[day - 1])}</b>
                    <span>${lessons.length} ${lessons.length === 1 ? "занятие" : lessons.length < 5 ? "занятия" : "занятий"}</span>
                </header>
                <div class="day-lessons">${rows}</div>
            </section>
        `);
    }

    root.innerHTML = parts.length
        ? parts.join("")
        : `<div class="empty-state"><p>На эту неделю занятий нет.</p></div>`;
}

async function loadSchedule() {
    const root = $("#schedule-root");
    if (!state.groupId) {
        state.group = null;
        state.lessons = [];
        renderMeta();
        renderSchedule();
        return;
    }

    root.innerHTML = `<div class="loading-state">Загрузка расписания…</div>`;
    try {
        const data = await api(
            `/api/public/schedule?group_id=${encodeURIComponent(state.groupId)}&week=${state.week}`,
        );
        state.group = data.group;
        state.lessons = data.lessons || [];
        renderMeta();
        renderSchedule();
        document.title = `Расписание ${data.group.name} — НСМК`;
    } catch (error) {
        state.group = null;
        state.lessons = [];
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

function startParamText(value) {
    if (typeof value === "string") {
        return value.trim();
    }
    if (value && typeof value === "object") {
        return String(value.value || value.payload || value.start_param || "").trim();
    }
    return "";
}

function groupIdFromStartParam(startParam) {
    const match = /^g_(\d+)$/.exec(startParam || "");
    if (!match) {
        return "";
    }
    const groupId = match[1];
    return state.groups.some((group) => String(group.id) === groupId) ? groupId : "";
}

async function readMaxLaunch() {
    const webApp = window.WebApp;
    const initData = webApp && typeof webApp.initData === "string" ? webApp.initData.trim() : "";
    if (!initData) {
        return "";
    }

    const staffLink = $("#staff-link");
    if (staffLink) {
        staffLink.classList.add("hidden");
    }

    const response = await fetch("/api/public/max/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ init_data: initData }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
        throw new Error(data.error || "Не удалось подтвердить запуск из MAX.");
    }

    const fromApp = startParamText(webApp.initDataUnsafe && webApp.initDataUnsafe.start_param);
    return startParamText(data.start_param) || fromApp;
}

function setGroup(groupId) {
    state.groupId = groupId ? String(groupId) : "";
    if (state.groupId) {
        localStorage.setItem(STORAGE_KEY, state.groupId);
    } else {
        localStorage.removeItem(STORAGE_KEY);
    }
    writeGroupToUrl(state.groupId);
    $("#group-select").value = state.groupId;
    loadSchedule();
}

async function init() {
    let startParam = "";
    try {
        startParam = await readMaxLaunch();
    } catch (error) {
        $("#schedule-root").innerHTML =
            `<div class="error-state">${esc(error.message)}</div>`;
        return;
    }

    const fromUrl = readGroupFromUrl();
    const fromStorage = localStorage.getItem(STORAGE_KEY) || "";

    try {
        state.groups = await api("/api/public/groups");
    } catch (error) {
        $("#schedule-root").innerHTML =
            `<div class="error-state">${esc(error.message)}</div>`;
        return;
    }

    fillGroups();
    const fromStart = groupIdFromStartParam(startParam);
    state.groupId = fromStart || fromUrl || fromStorage || "";

    $("#group-select").addEventListener("change", (event) => {
        setGroup(event.target.value);
    });

    document.querySelectorAll(".week-btn").forEach((button) => {
        button.addEventListener("click", () => {
            setWeek(Number(button.dataset.week));
        });
    });

    if (state.groupId) {
        $("#group-select").value = state.groupId;
        writeGroupToUrl(state.groupId);
        await loadSchedule();
    } else {
        renderSchedule();
    }
}

init();
