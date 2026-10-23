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
    substitutions: [],
    upcoming: [],
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

function coveredPeriods(day) {
    const covered = new Set();
    sheetsForDay(day).forEach((sheet) => {
        (sheet.rows || []).forEach((row) => {
            (row.periods || []).forEach((period) => covered.add(Number(period)));
        });
    });
    return covered;
}

function lessonCard(day, lesson) {
    const teacher1 = formatTeacher(lesson.teacher_name, lesson.teacher_short);
    const teacher2 = lesson.teacher2_name
        ? formatTeacher(lesson.teacher2_name, lesson.teacher2_short)
        : "";
    const teacher = teacher2 ? `${teacher1} / ${teacher2}` : teacher1;
    const rooms = [lesson.classroom_name || null, lesson.classroom2_name || null].filter(Boolean);
    const color = lesson.subject_color || "#a01914";
    return `
        <article class="lesson-row">
            <div class="lesson-period">
                <b>${esc(lesson.period)}</b>
                <small>${esc(bellTime(day, Number(lesson.period)))}</small>
            </div>
            <div class="lesson-body" style="--lesson-color:${esc(color)}">
                <div class="lesson-subject">${esc(lesson.subject_name || "Предмет не назначен")}</div>
                <div class="lesson-teacher">${esc(teacher)}</div>
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
    const instead = [row.old_subject, row.absent_teacher].filter(Boolean).join(", ");
    const subject = row.cancelled ? "Занятие снято" : row.new_subject || "Предмет не указан";
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
                ${row.new_teacher ? `<div class="lesson-teacher">${esc(row.new_teacher)}</div>` : ""}
                ${
                    row.new_room
                        ? `<div class="lesson-meta"><span class="chip chip-room">ауд. ${esc(row.new_room)}</span></div>`
                        : ""
                }
                ${
                    instead
                        ? `<div class="lesson-instead">${row.cancelled ? "было" : "вместо"}: ${esc(instead)}</div>`
                        : ""
                }
            </div>
        </article>
    `;
}

function renderChangeNotes() {
    const current = state.substitutions || [];
    const upcoming = state.upcoming || [];
    if (!current.length && !upcoming.length) {
        return "";
    }
    const currentHtml = current
        .map((sheet) => {
            const here = Number(sheet.week) === Number(state.week);
            const action = here
                ? `<span class="changes-here">показаны ниже</span>`
                : `<button type="button" data-switch-week="${sheet.week}">Показать ${sheet.week}-ю неделю</button>`;
            return `
                <div class="changes-banner-item">
                    <div>
                        <b>Замена на ${esc(sheet.date_label)}</b>
                        <span>${esc(sheet.weekday_label)}, ${sheet.week}-я неделя. Только в эту дату, потом снова обычные пары.</span>
                    </div>
                    <div class="changes-banner-actions">
                        ${action}
                        <a href="${esc(sheet.url)}">Таблица</a>
                    </div>
                </div>
            `;
        })
        .join("");
    const upcomingHtml = upcoming
        .map(
            (sheet) => `
                <div class="changes-banner-item is-later">
                    <div>
                        <b>${esc(sheet.date_label)}</b>
                        <span>${esc(sheet.weekday_label)}, ${sheet.week}-я неделя. Сейчас в сетке обычные пары — замена откроется только на той неделе.</span>
                    </div>
                    <div class="changes-banner-actions">
                        <a href="${esc(sheet.url)}">Таблица</a>
                    </div>
                </div>
            `,
        )
        .join("");
    return `<section class="changes-banner">${currentHtml}${upcomingHtml}</section>`;
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

    const banner = renderChangeNotes();
    const hasLessons = state.lessons.length > 0;
    const hasCurrent = (state.substitutions || []).some(
        (sheet) => Number(sheet.week) === Number(state.week),
    );
    if (!hasLessons && !hasCurrent && !banner) {
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
        const covered = coveredPeriods(day);
        const items = [];
        lessons.forEach((lesson) => {
            if (covered.has(Number(lesson.period))) {
                return;
            }
            items.push({
                period: Number(lesson.period),
                html: lessonCard(day, lesson),
            });
        });
        sheetsForDay(day).forEach((sheet) => {
            (sheet.rows || []).forEach((row) => {
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
    root.innerHTML = `${banner}${parts.length ? parts.join("") : empty}`;
}

async function loadSchedule() {
    const root = $("#schedule-root");
    if (!state.groupId) {
        state.group = null;
        state.lessons = [];
        state.substitutions = [];
        state.upcoming = [];
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
        state.substitutions = data.substitutions || [];
        state.upcoming = data.upcoming_substitutions || [];
        renderMeta();
        renderSchedule();
        document.title = `Расписание ${data.group.name} — НСМК`;
    } catch (error) {
        state.group = null;
        state.lessons = [];
        state.substitutions = [];
        state.upcoming = [];
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

    $("#schedule-root").addEventListener("click", (event) => {
        const button = event.target.closest("[data-switch-week]");
        if (!button) {
            return;
        }
        setWeek(Number(button.dataset.switchWeek));
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
