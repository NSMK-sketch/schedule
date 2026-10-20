const state = {
    user: null,
    week: 1,
    group: "",
    search: "",
    view: "schedule",
    directory: "groups",
    directorySearch: "",
    groups: [],
    teachers: [],
    subjects: [],
    classrooms: [],
    teacher_subjects: [],
    lessons: [],
    expandedTeachers: new Set(),
};

const DIRECTORY_META = {
    groups: {
        title: "Группы",
        description: "Учебные группы: название, специальность и курс",
        columns: [
            { key: "name", label: "Название" },
            { key: "speciality", label: "Специальность" },
            { key: "course", label: "Курс" },
        ],
    },
    teachers: {
        title: "Преподаватели",
        description: "Преподаватели и привязанные дисциплины",
        columns: [
            { key: "full_name", label: "ФИО" },
            { key: "short_name", label: "Сокращение" },
            { key: "color", label: "Цвет" },
            { key: "subjects", label: "Дисциплины" },
        ],
    },
    subjects: {
        title: "Дисциплины",
        description: "Учебные дисциплины и краткие обозначения",
        columns: [
            { key: "name", label: "Название" },
            { key: "short_name", label: "Кратко" },
            { key: "color", label: "Цвет" },
        ],
    },
    classrooms: {
        title: "Аудитории",
        description: "Кабинеты и лабораторные аудитории",
        columns: [
            { key: "name", label: "Номер" },
            { key: "room_type", label: "Тип" },
            { key: "seats", label: "Мест" },
        ],
    },
};

const days = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
];

const bellSchedule = {
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

function getBellTime(weekday, period) {
    const schedule = weekday === 1 ? bellSchedule.monday : bellSchedule.regular;
    return schedule[period - 1] || "—";
}

function getTeacherShortName(fullName) {
    return String(fullName || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean)
        .map((part) => part[0].toUpperCase())
        .join("")
        .slice(0, 4);
}

/** "Морозова Елена Викторовна" → "Морозова Е.В." */
function formatTeacherSurnameInitials(fullName) {
    const parts = String(fullName || "")
        .trim()
        .split(/\s+/)
        .filter(Boolean);

    if (!parts.length) {
        return "";
    }

    const surname = parts[0];
    const initials = parts
        .slice(1)
        .map((part) => `${part[0].toUpperCase()}.`)
        .join("");

    return initials ? `${surname} ${initials}` : surname;
}

const $ = (selector) => document.querySelector(selector);

function applyTheme(theme) {
    const normalized = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = normalized;
    localStorage.setItem("schedule-theme", normalized);

    const icon = $("#theme-icon");
    const button = $("#theme-toggle");

    if (icon) icon.textContent = normalized === "dark" ? "☀" : "☾";
    if (button) {
        button.setAttribute(
            "aria-label",
            normalized === "dark" ? "Переключить на светлую тему" : "Переключить на тёмную тему"
        );
    }
}

function setupTheme() {
    const saved = localStorage.getItem("schedule-theme") || "dark";
    applyTheme(saved);

    const button = $("#theme-toggle");
    if (!button) return;

    button.addEventListener("click", () => {
        const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
        applyTheme(next);
    });
}

document.addEventListener("DOMContentLoaded", setupTheme);

async function parseApiResponse(response) {
    const text = await response.text();
    let data = {};

    try {
        data = text ? JSON.parse(text) : {};
    } catch {
        data = { error: "Сервер вернул некорректный ответ." };
    }

    if (!response.ok) {
        throw new Error(data.error || "Ошибка запроса.");
    }

    return data;
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
    });

    return parseApiResponse(response);
}

async function apiUpload(url, formData) {
    const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        body: formData,
    });

    return parseApiResponse(response);
}

function toast(message, type = "success") {
    if (type === "error" && String(message).startsWith("Конфликт:")) {
        showConflictDialog(message);
        return;
    }

    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.textContent = message;
    $("#toast-container").append(node);

    setTimeout(() => node.remove(), 3200);
}


function showConflictDialog(message) {
    const dialog = $("#conflict-dialog");
    if (!dialog) {
        return;
    }

    $("#conflict-message").textContent = message.replace(/^Конфликт:\s*/, "");
    if (dialog.open) {
        dialog.close();
    }
    dialog.showModal();
}

function confirmDialog(message, title = "Удаление", confirmLabel = "Удалить") {
    return new Promise((resolve) => {
        const dialog = $("#confirm-dialog");
        const form = $("#confirm-form");
        const titleNode = $("#confirm-title");
        const messageNode = $("#confirm-message");
        const confirmButton = form.querySelector('button[type="submit"]');

        titleNode.textContent = title;
        messageNode.textContent = message;
        if (confirmButton) {
            confirmButton.textContent = confirmLabel;
        }

        const finish = (result) => {
            dialog.close();
            resolve(result);
        };

        const handleSubmit = (event) => {
            event.preventDefault();
            cleanup();
            finish(true);
        };

        const handleCancel = () => {
            cleanup();
            finish(false);
        };

        const handleBackdropClose = () => {
            cleanup();
            resolve(false);
        };

        const cleanup = () => {
            form.removeEventListener("submit", handleSubmit);
            dialog.querySelectorAll("[data-confirm-cancel]").forEach((button) => {
                button.removeEventListener("click", handleCancel);
            });
            dialog.removeEventListener("cancel", handleBackdropClose);
        };

        form.addEventListener("submit", handleSubmit);
        dialog.querySelectorAll("[data-confirm-cancel]").forEach((button) => {
            button.addEventListener("click", handleCancel);
        });
        dialog.addEventListener("cancel", handleBackdropClose);
        dialog.showModal();
    });
}

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    })[char]);
}

function isAdmin() {
    return state.user?.role === "admin";
}

function roleTitle(role) {
    return {
        admin: "Администратор",
        teacher: "Преподаватель",
    }[role] || role;
}

async function login(event) {
    event.preventDefault();

    const username = $("#login-username").value.trim();
    const password = $("#login-password").value;

    if (!username || !password.trim()) {
        toast("Логин и пароль не могут быть пустыми.", "error");
        return;
    }

    try {
        state.user = await api("/api/auth/login", {
            method: "POST",
            body: JSON.stringify({ username, password }),
        });

        showApp();
        await loadData();
        toast("Вход выполнен.");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function logout() {
    try {
        await api("/api/auth/logout", { method: "POST" });
    } finally {
        state.user = null;
        $("#app-shell").classList.add("hidden");
        $("#login-screen").classList.remove("hidden");
    }
}

function showApp() {
    $("#login-screen").classList.add("hidden");
    $("#app-shell").classList.remove("hidden");

    document
        .querySelectorAll(".admin-only")
        .forEach((node) => node.classList.toggle("hidden", !isAdmin()));
}

function setDirectoriesOpen(open) {
    const toggle = $("#directories-toggle");
    const menu = $("#directories-menu");
    if (!toggle || !menu) {
        return;
    }

    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.classList.toggle("open", open);
    menu.hidden = !open;
    const chevron = toggle.querySelector(".side-accordion-chevron");
    if (chevron) {
        chevron.textContent = open ? "▾" : "▸";
    }
}

async function loadData() {
    const data = await api("/api/bootstrap");
    Object.assign(state, data);

    await loadLessons();
    render();
}

async function loadLessons() {
    const params = new URLSearchParams({ week: state.week });
    state.lessons = await api(`/api/lessons?${params}`);
}

function visibleGroups() {
    if (!state.group) {
        return state.groups;
    }
    return state.groups.filter((group) => String(group.id) === String(state.group));
}

function shortTeacherName(lesson, which = 1) {
    if (which === 2) {
        return (
            formatTeacherSurnameInitials(lesson.teacher2_name) ||
            lesson.teacher2_short ||
            ""
        );
    }
    return formatTeacherSurnameInitials(lesson.teacher_name) || lesson.teacher_short || "";
}

function isSplitLesson(lesson) {
    return Boolean(lesson && lesson.teacher2_id);
}

function fillClassroomSelect(selector, selectedId = "") {
    const node = $(selector);
    if (!node) {
        return;
    }
    node.innerHTML = `
        <option value="">Без аудитории</option>
        ${state.classrooms
            .map((item) => `<option value="${item.id}">${esc(item.name)}</option>`)
            .join("")}
    `;
    setSelectValue(node, selectedId || "");
}

function setLessonSplitMode(enabled) {
    const split = Boolean(enabled);
    const checkbox = $("#lesson-split");
    if (checkbox) {
        checkbox.checked = split;
    }
    $("#lesson-teacher2-wrap")?.classList.toggle("hidden", !split);
    $("#lesson-classroom2-wrap")?.classList.toggle("hidden", !split);
}

function render() {
    renderScheduleGroups();
    renderSchedule();
    renderTeachersPanel();
    renderDirectoryCounts();
    renderDirectoryTable();

    $("#stat-lessons").textContent = state.lessons.length;
    $("#stat-groups").textContent = state.groups.length;
    $("#stat-teachers").textContent = state.teachers.length;
}

function renderDirectoryCounts() {
    document.querySelectorAll("[data-count]").forEach((node) => {
        const key = node.dataset.count;
        node.textContent = String((state[key] || []).length);
    });
}

function switchView(view, directory = null) {
    if (view === "directory" && !isAdmin()) {
        return;
    }

    state.view = view;
    if (directory) {
        state.directory = directory;
        state.directorySearch = "";
        const searchInput = $("#directory-search");
        if (searchInput) {
            searchInput.value = "";
        }
    }

    document.querySelectorAll("[data-view]").forEach((item) => {
        const isSchedule = item.dataset.view === "schedule" && view === "schedule";
        const isDirectory =
            item.dataset.view === "directory" &&
            view === "directory" &&
            item.dataset.directory === state.directory;
        item.classList.toggle("active", Boolean(isSchedule || isDirectory));
    });

    $("#schedule-view").classList.toggle("hidden", view !== "schedule");
    $("#directories-view").classList.toggle("hidden", view !== "directory");

    const tools = $("#side-schedule-tools");
    if (tools) {
        tools.classList.toggle("hidden", view !== "schedule");
    }

    if (view === "directory") {
        setDirectoriesOpen(true);
        renderDirectoryTable();
    }
}

function renderScheduleGroups() {
    const select = $("#schedule-groups-list");
    if (!select) {
        return;
    }

    const previous = state.group === "" ? "" : String(state.group);
    select.innerHTML = "";

    const allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "Все группы";
    select.append(allOption);

    state.groups.forEach((group) => {
        const option = document.createElement("option");
        option.value = String(group.id);
        option.textContent = group.name;
        select.append(option);
    });

    const hasSelected =
        previous === "" || state.groups.some((group) => String(group.id) === previous);
    select.value = hasSelected ? previous : "";
    if (!hasSelected) {
        state.group = "";
    }
}

function setScheduleColumns(groupCount) {
    const columns = `112px repeat(${Math.max(groupCount, 1)}, minmax(150px, 1fr))`;
    const head = $("#schedule-head");
    const body = $("#schedule-body");
    if (head) {
        head.style.gridTemplateColumns = columns;
    }
    if (body) {
        body.style.setProperty("--schedule-columns", columns);
    }
    document.querySelectorAll(".schedule-row, .schedule-day-row").forEach((row) => {
        row.style.gridTemplateColumns = columns;
    });
}

function renderSchedule() {
    preventScheduleContainerDrag();

    const groups = visibleGroups();
    const head = $("#schedule-head");
    const body = $("#schedule-body");
    head.innerHTML = "";
    body.innerHTML = "";

    const corner = document.createElement("div");
    corner.className = "head-day";
    corner.innerHTML = "<b>День / пара</b>";
    head.append(corner);

    if (!groups.length) {
        const empty = document.createElement("div");
        empty.className = "schedule-empty-head";
        empty.textContent = "Добавьте учебные группы в справочнике";
        head.append(empty);
        setScheduleColumns(1);
        return;
    }

    groups.forEach((group) => {
        const cell = document.createElement("div");
        cell.className = "head-group";
        cell.innerHTML = `<b>${esc(group.name)}</b>`;
        head.append(cell);
    });

    setScheduleColumns(groups.length);

    const query = state.search.toLowerCase().trim();
    const filteredLessons = state.lessons.filter((lesson) => {
        if (!query) {
            return true;
        }
        return [
            lesson.subject_name,
            lesson.subject_short,
            lesson.group_name,
            lesson.teacher_name,
            lesson.teacher_short,
            lesson.teacher2_name,
            lesson.teacher2_short,
            lesson.classroom_name,
            lesson.classroom2_name,
        ]
            .join(" ")
            .toLowerCase()
            .includes(query);
    });

    for (let weekday = 1; weekday <= 6; weekday += 1) {
        const dayRow = document.createElement("div");
        dayRow.className = "schedule-day-row";
        dayRow.style.gridTemplateColumns = `112px repeat(${groups.length}, minmax(150px, 1fr))`;

        const dayLabel = document.createElement("div");
        dayLabel.className = "day-banner";
        dayLabel.innerHTML = `
            <b>${days[weekday - 1]}</b>
            ${weekday === 1 ? "<small>Классный час · 09:00–09:50</small>" : ""}
        `;
        dayRow.append(dayLabel);

        const daySpan = document.createElement("div");
        daySpan.className = "day-banner-span";
        daySpan.style.gridColumn = `2 / span ${groups.length}`;
        dayRow.append(daySpan);
        body.append(dayRow);

        for (let period = 1; period <= 4; period += 1) {
            const row = document.createElement("div");
            row.className = "schedule-row";
            row.style.gridTemplateColumns = `112px repeat(${groups.length}, minmax(150px, 1fr))`;

            const periodCell = document.createElement("div");
            periodCell.className = "period-cell";
            periodCell.innerHTML = `
                <b>${period}</b>
                <small>${esc(getBellTime(weekday, period))}</small>
            `;
            row.append(periodCell);

            groups.forEach((group) => {
                row.append(createScheduleCell(weekday, period, group.id));
            });

            body.append(row);
        }
    }

    filteredLessons.forEach((lesson) => {
        const cell = document.querySelector(
            `.schedule-cell[data-weekday="${lesson.weekday}"][data-period="${lesson.period}"][data-group-id="${lesson.group_id}"]`,
        );
        if (cell) {
            cell.append(createCard(lesson));
        }
    });

}

function preventScheduleContainerDrag() {
    const schedule = document.querySelector(".schedule-wrap");

    if (!schedule || schedule.dataset.dragGuardReady === "true") {
        return;
    }

    schedule.dataset.dragGuardReady = "true";

    schedule.addEventListener("dragstart", (event) => {
        const draggableItem = event.target.closest(
            ".lesson-card, .teacher-subject-draggable, .teacher-main"
        );

        if (!draggableItem) {
            event.preventDefault();
        }
    });

    schedule.addEventListener("mousedown", (event) => {
        if (event.button === 0 && !event.target.closest(
            ".lesson-card, .teacher-subject-draggable, .teacher-main, button, input, select"
        )) {
            window.getSelection()?.removeAllRanges();
        }
    });
}

function setupScheduleEdgeScroll() {
    const wrap = $("#schedule-wrap");
    if (!wrap || wrap.dataset.edgeScrollReady === "true") {
        return;
    }

    wrap.dataset.edgeScrollReady = "true";

    const EDGE = 56;
    const MAX_SPEED = 22;
    let velocityX = 0;
    let velocityY = 0;
    let dragging = false;
    let frameId = null;

    const clearEdgeClasses = () => {
        wrap.classList.remove(
            "edge-scroll-left",
            "edge-scroll-right",
            "edge-scroll-top",
            "edge-scroll-bottom",
        );
    };

    const stop = () => {
        dragging = false;
        velocityX = 0;
        velocityY = 0;
        clearEdgeClasses();
        if (frameId) {
            cancelAnimationFrame(frameId);
            frameId = null;
        }
    };

    const tick = () => {
        if (!dragging || (!velocityX && !velocityY)) {
            frameId = null;
            return;
        }

        wrap.scrollLeft += velocityX;
        wrap.scrollTop += velocityY;
        frameId = requestAnimationFrame(tick);
    };

    const updateFromPoint = (clientX, clientY) => {
        if (!dragging) {
            return;
        }

        const rect = wrap.getBoundingClientRect();
        const x = clientX - rect.left;
        const y = clientY - rect.top;

        if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
            velocityX = 0;
            velocityY = 0;
            clearEdgeClasses();
            return;
        }

        velocityX = 0;
        velocityY = 0;

        if (x < EDGE) {
            velocityX = -MAX_SPEED * (1 - x / EDGE);
        } else if (x > rect.width - EDGE) {
            velocityX = MAX_SPEED * (1 - (rect.width - x) / EDGE);
        }

        if (y < EDGE) {
            velocityY = -MAX_SPEED * (1 - y / EDGE);
        } else if (y > rect.height - EDGE) {
            velocityY = MAX_SPEED * (1 - (rect.height - y) / EDGE);
        }

        wrap.classList.toggle("edge-scroll-left", velocityX < 0);
        wrap.classList.toggle("edge-scroll-right", velocityX > 0);
        wrap.classList.toggle("edge-scroll-top", velocityY < 0);
        wrap.classList.toggle("edge-scroll-bottom", velocityY > 0);

        if ((velocityX || velocityY) && !frameId) {
            frameId = requestAnimationFrame(tick);
        }
    };

    const isScheduleDrag = (event) => {
        const types = event.dataTransfer?.types;
        if (!types) {
            return false;
        }
        const list = [...types];
        return (
            list.includes("lesson-id") ||
            list.includes("teacher-id") ||
            list.includes("subject-id") ||
            list.includes("text/plain")
        );
    };

    document.addEventListener("dragstart", (event) => {
        const source = event.target.closest(
            ".lesson-card, .teacher-subject-draggable, .teacher-main",
        );
        if (!source) {
            return;
        }
        dragging = true;
    });

    document.addEventListener("dragend", stop);

    wrap.addEventListener("dragover", (event) => {
        if (!dragging && !isScheduleDrag(event)) {
            return;
        }
        dragging = true;
        event.preventDefault();
        updateFromPoint(event.clientX, event.clientY);
    });

    wrap.addEventListener("dragleave", (event) => {
        if (!wrap.contains(event.relatedTarget)) {
            velocityX = 0;
            velocityY = 0;
            clearEdgeClasses();
        }
    });

    wrap.addEventListener("drop", stop);
}


function createScheduleCell(weekday, period, groupId) {
    const cell = document.createElement("div");
    cell.className = "schedule-cell";
    cell.dataset.weekday = weekday;
    cell.dataset.period = period;
    cell.dataset.groupId = groupId;

    if (!isAdmin()) {
        return cell;
    }

    cell.addEventListener("dragover", (event) => {
        event.preventDefault();
        cell.classList.add("drag-over");
    });

    cell.addEventListener("dragleave", () => {
        cell.classList.remove("drag-over");
    });

    cell.addEventListener("drop", async (event) => {
        event.preventDefault();
        cell.classList.remove("drag-over");

        const lessonId = Number(event.dataTransfer.getData("lesson-id"));
        if (lessonId) {
            await moveLesson(lessonId, weekday, period, groupId);
            return;
        }

        const teacherId = Number(event.dataTransfer.getData("teacher-id"));
        const subjectRaw = event.dataTransfer.getData("subject-id");
        const subjectId = subjectRaw ? Number(subjectRaw) : null;

        if (teacherId && subjectId) {
            openLesson({
                week: state.week,
                weekday,
                period,
                teacher_id: teacherId,
                subject_id: subjectId,
                group_id: groupId,
            });
            return;
        }

        if (teacherId) {
            await placeTeacherWithoutSubject(teacherId, weekday, period, groupId);
        }
    });

    cell.addEventListener("dblclick", () => {
        openLesson({
            week: state.week,
            weekday,
            period,
            group_id: groupId,
        });
    });

    return cell;
}

async function placeTeacherWithoutSubject(teacherId, weekday, period, groupId) {
    try {
        await api("/api/lessons", {
            method: "POST",
            body: JSON.stringify({
                week: state.week,
                weekday,
                period,
                group_id: groupId,
                teacher_id: teacherId,
                subject_id: null,
                classroom_id: null,
                lesson_type: "Лекция",
                note: "",
            }),
        });
        toast("Преподаватель добавлен. Укажите предмет.");
        await loadLessons();
        render();
    } catch (error) {
        toast(error.message, "error");
    }
}

function createCard(lesson) {
    const card = document.createElement("article");
    const hasSubject = Boolean(lesson.subject_id && lesson.subject_name);
    const split = isSplitLesson(lesson);
    card.className = `lesson-card${hasSubject ? "" : " lesson-card-pending"}`;
    card.draggable = isAdmin();
    card.style.setProperty(
        "--lesson-color",
        lesson.teacher_color || lesson.subject_color || "#6366f1",
    );

    const deleteButton = isAdmin()
        ? '<button class="card-delete" title="Удалить">×</button>'
        : "";
    const teacher1 = shortTeacherName(lesson, 1);
    const teacher2 = split ? shortTeacherName(lesson, 2) : "";
    const teacherLabel = split ? `${teacher1} / ${teacher2}` : teacher1;
    const subject = hasSubject ? lesson.subject_name : "Предмет не назначен";
    const rooms = [
        lesson.classroom_name || null,
        split ? lesson.classroom2_name || null : null,
    ].filter(Boolean);
    const roomLabel = rooms.length ? `ауд. ${rooms.join(" / ")}` : "";

    card.innerHTML = `
        ${deleteButton}
        <div class="lesson-teacher">${esc(teacherLabel)}</div>
        <div class="lesson-subject${hasSubject ? "" : " lesson-subject-pending"}">${esc(subject)}</div>
        ${roomLabel ? `<div class="lesson-room">${esc(roomLabel)}</div>` : ""}
    `;
    card.title = [teacherLabel, subject, roomLabel || null].filter(Boolean).join(" · ");

    if (isAdmin()) {
        card.addEventListener("dragstart", (event) => {
            event.dataTransfer.setData("lesson-id", lesson.id);
        });

        card.addEventListener("dblclick", (event) => {
            event.stopPropagation();
            openLesson(lesson);
        });

        card.querySelector(".card-delete").addEventListener("click", async (event) => {
            event.stopPropagation();

            if (!(await confirmDialog("Удалить это занятие?"))) {
                return;
            }

            try {
                await api(`/api/lessons/${lesson.id}`, { method: "DELETE" });
                toast("Занятие удалено.");
                await loadLessons();
                render();
            } catch (error) {
                toast(error.message, "error");
            }
        });
    }

    return card;
}

async function moveLesson(id, weekday, period, groupId) {
    if (!isAdmin()) {
        return;
    }

    const lesson = state.lessons.find((item) => item.id === id);
    if (!lesson) {
        return;
    }

    try {
        await api(`/api/lessons/${id}`, {
            method: "PUT",
            body: JSON.stringify({
                ...lesson,
                weekday,
                period,
                group_id: groupId,
            }),
        });

        toast("Занятие перемещено.");
        await loadLessons();
        render();
    } catch (error) {
        toast(error.message, "error");
    }
}

function fillSelect(id, items, label) {
    const select = $(id);
    if (!select) {
        return;
    }
    select.innerHTML = items
        .map((item) => `<option value="${item.id}">${esc(item[label])}</option>`)
        .join("");
    refreshSearchableSelect(select);
}

function ensureSearchableSelect(select) {
    if (!select || !select.classList.contains("js-searchable")) {
        return null;
    }
    if (select.closest(".searchable-select")) {
        return select.closest(".searchable-select");
    }

    const wrap = document.createElement("div");
    wrap.className = "searchable-select";
    select.parentNode.insertBefore(wrap, select);
    wrap.append(select);
    select.classList.add("searchable-select-native");
    select.tabIndex = -1;

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "searchable-select-toggle";
    toggle.setAttribute("aria-haspopup", "listbox");
    toggle.setAttribute("aria-expanded", "false");

    const panel = document.createElement("div");
    panel.className = "searchable-select-panel hidden";

    const filter = document.createElement("input");
    filter.type = "search";
    filter.className = "searchable-select-filter";
    filter.placeholder = "Поиск…";
    filter.autocomplete = "off";

    const list = document.createElement("ul");
    list.className = "searchable-select-options";
    list.setAttribute("role", "listbox");

    panel.append(filter, list);
    wrap.append(toggle, panel);

    const closePanel = () => {
        panel.classList.add("hidden");
        toggle.setAttribute("aria-expanded", "false");
        filter.value = "";
        renderSearchableOptions(select);
    };

    const openPanel = () => {
        document.querySelectorAll(".searchable-select-panel:not(.hidden)").forEach((open) => {
            if (open !== panel) {
                open.classList.add("hidden");
                open
                    .closest(".searchable-select")
                    ?.querySelector(".searchable-select-toggle")
                    ?.setAttribute("aria-expanded", "false");
            }
        });
        panel.classList.remove("hidden");
        toggle.setAttribute("aria-expanded", "true");
        filter.value = "";
        renderSearchableOptions(select);
        requestAnimationFrame(() => filter.focus());
    };

    toggle.addEventListener("click", (event) => {
        event.preventDefault();
        if (select.disabled) {
            return;
        }
        if (panel.classList.contains("hidden")) {
            openPanel();
        } else {
            closePanel();
        }
    });

    filter.addEventListener("input", () => renderSearchableOptions(select));
    filter.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            closePanel();
            toggle.focus();
        }
        if (event.key === "Enter") {
            event.preventDefault();
            const first = list.querySelector("[data-value]");
            if (first) {
                first.click();
            }
        }
    });

    list.addEventListener("click", (event) => {
        const option = event.target.closest("[data-value]");
        if (!option) {
            return;
        }
        select.value = option.dataset.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        syncSearchableSelectDisplay(select);
        closePanel();
    });

    document.addEventListener("click", (event) => {
        if (!wrap.contains(event.target)) {
            closePanel();
        }
    });

    select.addEventListener("change", () => syncSearchableSelectDisplay(select));
    syncSearchableSelectDisplay(select);
    return wrap;
}

function renderSearchableOptions(select) {
    const wrap = select.closest(".searchable-select");
    if (!wrap) {
        return;
    }
    const filter = wrap.querySelector(".searchable-select-filter");
    const list = wrap.querySelector(".searchable-select-options");
    const query = (filter?.value || "").trim().toLowerCase();

    const options = [...select.options].filter((option) => {
        if (!query) {
            return true;
        }
        return option.textContent.toLowerCase().includes(query);
    });

    if (!options.length) {
        list.innerHTML = '<li class="searchable-select-empty">Ничего не найдено</li>';
        return;
    }

    list.innerHTML = options
        .map((option) => {
            const selected = option.value === select.value ? " is-selected" : "";
            return `<li class="searchable-select-option${selected}" role="option" data-value="${esc(option.value)}">${esc(option.textContent)}</li>`;
        })
        .join("");
}

function syncSearchableSelectDisplay(select) {
    const wrap = select.closest(".searchable-select");
    if (!wrap) {
        return;
    }
    const toggle = wrap.querySelector(".searchable-select-toggle");
    const selected = select.options[select.selectedIndex];
    const label = selected ? selected.textContent : "Выберите…";
    toggle.textContent = label || "Выберите…";
    toggle.classList.toggle("is-placeholder", !select.value);
    toggle.disabled = Boolean(select.disabled);
}

function refreshSearchableSelect(selectOrId) {
    const select =
        typeof selectOrId === "string" ? $(selectOrId) : selectOrId;
    if (!select) {
        return;
    }
    ensureSearchableSelect(select);
    syncSearchableSelectDisplay(select);
}

function setSelectValue(selectOrId, value) {
    const select =
        typeof selectOrId === "string" ? $(selectOrId) : selectOrId;
    if (!select) {
        return;
    }
    select.value = value == null ? "" : String(value);
    refreshSearchableSelect(select);
}

function getTeacherSubjectIds(teacherId) {
    return new Set(
        state.teacher_subjects
            .filter((link) => Number(link.teacher_id) === Number(teacherId))
            .map((link) => Number(link.subject_id)),
    );
}

function updateLessonSubjects(selectedSubjectId = null, preferEmpty = false) {
    const teacherId = Number($("#lesson-teacher").value);
    const subjectSelect = $("#lesson-subject");
    const subjectIds = getTeacherSubjectIds(teacherId);
    const subjects = state.subjects.filter((subject) => subjectIds.has(Number(subject.id)));

    const options = [
        '<option value="">Предмет не выбран</option>',
        ...subjects.map(
            (subject) => `<option value="${subject.id}">${esc(subject.name)}</option>`,
        ),
    ];
    subjectSelect.innerHTML = options.join("");
    subjectSelect.disabled = false;

    if (
        selectedSubjectId &&
        subjects.some((subject) => Number(subject.id) === Number(selectedSubjectId))
    ) {
        setSelectValue(subjectSelect, selectedSubjectId);
    } else if (preferEmpty || !subjects.length) {
        setSelectValue(subjectSelect, "");
    } else {
        setSelectValue(subjectSelect, subjects[0].id);
    }
}

function openLesson(lesson = {}) {
    if (!isAdmin()) {
        return;
    }

    $("#lesson-form").reset();
    $("#lesson-id").value = lesson.id || "";
    $("#lesson-dialog-title").textContent = lesson.id
        ? "Редактировать занятие"
        : "Новое занятие";
    $("#lesson-week").value = lesson.week || state.week;
    $("#lesson-day").value = lesson.weekday || 1;
    $("#lesson-period").value = lesson.period || 1;

    fillSelect("#lesson-group", state.groups, "name");
    fillSelect("#lesson-teacher", state.teachers, "full_name");
    fillSelect("#lesson-teacher2", state.teachers, "full_name");
    fillClassroomSelect("#lesson-classroom", lesson.classroom_id || "");
    fillClassroomSelect("#lesson-classroom2", lesson.classroom2_id || "");

    setSelectValue("#lesson-group", lesson.group_id || state.groups[0]?.id || "");
    setSelectValue(
        "#lesson-teacher",
        lesson.teacher_id || state.teachers[0]?.id || "",
    );

    const split = isSplitLesson(lesson);
    setLessonSplitMode(split);
    if (split) {
        setSelectValue("#lesson-teacher2", lesson.teacher2_id);
    } else if (state.teachers.length > 1) {
        const primary = String(lesson.teacher_id || state.teachers[0]?.id || "");
        const other = state.teachers.find((item) => String(item.id) !== primary);
        setSelectValue("#lesson-teacher2", other ? other.id : "");
    }

    const preferEmptySubject =
        lesson.id
            ? !lesson.subject_id
            : Boolean(lesson.teacher_id && !lesson.subject_id);
    updateLessonSubjects(lesson.subject_id || null, preferEmptySubject);
    $("#lesson-type").value = lesson.lesson_type || "Лекция";
    $("#lesson-note").value = lesson.note || "";

    $("#delete-lesson-button").classList.toggle("hidden", !lesson.id);
    $("#lesson-dialog").showModal();
}

async function saveLesson(event) {
    event.preventDefault();

    if (!isAdmin()) {
        toast("Изменять расписание может только администратор.", "error");
        return;
    }

    const id = $("#lesson-id").value;
    const subjectValue = $("#lesson-subject").value;
    const split = Boolean($("#lesson-split")?.checked);
    const data = {
        week: Number($("#lesson-week").value),
        weekday: Number($("#lesson-day").value),
        period: Number($("#lesson-period").value),
        group_id: Number($("#lesson-group").value),
        subject_id: subjectValue ? Number(subjectValue) : null,
        teacher_id: Number($("#lesson-teacher").value),
        teacher2_id: split && $("#lesson-teacher2").value
            ? Number($("#lesson-teacher2").value)
            : null,
        classroom_id: $("#lesson-classroom").value
            ? Number($("#lesson-classroom").value)
            : null,
        classroom2_id: split && $("#lesson-classroom2").value
            ? Number($("#lesson-classroom2").value)
            : null,
        lesson_type: $("#lesson-type").value.trim(),
        note: $("#lesson-note").value.trim(),
    };

    if (!data.group_id || !data.teacher_id) {
        toast("Выберите группу и преподавателя.", "error");
        return;
    }

    if (split && !data.teacher2_id) {
        toast("Выберите преподавателя для второй подгруппы.", "error");
        return;
    }

    if (split && data.teacher2_id === data.teacher_id) {
        toast("Для подгрупп нужны два разных преподавателя.", "error");
        return;
    }

    if (!data.lesson_type) {
        toast("Укажите тип занятия.", "error");
        return;
    }

    try {
        await api(id ? `/api/lessons/${id}` : "/api/lessons", {
            method: id ? "PUT" : "POST",
            body: JSON.stringify(data),
        });

        $("#lesson-dialog").close();
        toast(id ? "Занятие обновлено." : "Занятие добавлено.");
        state.week = data.week;
        updateWeekButtons();
        await loadLessons();
        render();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function deleteCurrentLesson() {
    const id = $("#lesson-id").value;

    if (!id || !isAdmin()) {
        return;
    }

    if (!(await confirmDialog("Удалить это занятие?"))) {
        return;
    }

    try {
        await api(`/api/lessons/${id}`, { method: "DELETE" });
        $("#lesson-dialog").close();
        toast("Занятие удалено.");
        await loadLessons();
        render();
    } catch (error) {
        toast(error.message, "error");
    }
}

function renderTeachersPanel() {
    const container = $("#teachers-panel-list");
    if (!container) {
        return;
    }
    container.innerHTML = "";

    const query = $("#teacher-search")?.value.toLowerCase().trim() || "";

    state.teachers
        .filter((teacher) => `${teacher.full_name} ${teacher.short_name}`.toLowerCase().includes(query))
        .forEach((teacher) => {
            const item = document.createElement("div");
            item.className = "teacher-item";
            const displayName = formatTeacherSurnameInitials(teacher.full_name) || teacher.full_name;

            const assignedSubjects = state.teacher_subjects
                .filter((link) => Number(link.teacher_id) === Number(teacher.id))
                .map((link) => state.subjects.find((subject) => Number(subject.id) === Number(link.subject_id)))
                .filter(Boolean);

            item.innerHTML = `
                <button type="button" class="teacher-main" aria-expanded="${state.expandedTeachers.has(Number(teacher.id))}" title="${isAdmin() ? "Перетащите преподавателя в расписание" : esc(displayName)}">
                    <span class="teacher-avatar" style="--teacher-color:${esc(teacher.color || "#6366f1")}">
                        ${esc((teacher.short_name || getTeacherShortName(teacher.full_name) || "").slice(0, 3).toUpperCase())}
                    </span>
                    <span class="teacher-main-text">
                        <b>${esc(displayName)}</b>
                        <small>${esc(assignedSubjects.length ? `${assignedSubjects.length} дисц.` : "нет дисциплин")}</small>
                    </span>
                    <span class="teacher-chevron">${state.expandedTeachers.has(Number(teacher.id)) ? "▾" : "▸"}</span>
                </button>
                <div class="teacher-subject-list ${state.expandedTeachers.has(Number(teacher.id)) ? "open" : ""}"></div>
            `;

            const subjectList = item.querySelector(".teacher-subject-list");
            if (!assignedSubjects.length) {
                subjectList.innerHTML = '<span class="teacher-no-subjects">Нет привязанных дисциплин</span>';
            } else {
                assignedSubjects.forEach((subject) => {
                    const subjectItem = document.createElement("div");
                    subjectItem.className = "teacher-subject-draggable";
                    subjectItem.draggable = isAdmin();
                    subjectItem.textContent = subject.name;
                    subjectItem.title = isAdmin() ? "Перетащите дисциплину в расписание" : subject.name;

                    if (isAdmin()) {
                        subjectItem.addEventListener("dragstart", (event) => {
                            event.stopPropagation();
                            event.dataTransfer.setData("teacher-id", String(teacher.id));
                            event.dataTransfer.setData("subject-id", String(subject.id));
                            event.dataTransfer.effectAllowed = "copy";
                        });
                    }

                    subjectList.append(subjectItem);
                });
            }

            const mainButton = item.querySelector(".teacher-main");
            if (isAdmin()) {
                mainButton.draggable = true;
                mainButton.addEventListener("dragstart", (event) => {
                    event.dataTransfer.setData("teacher-id", String(teacher.id));
                    event.dataTransfer.effectAllowed = "copy";
                    mainButton.classList.add("is-dragging");
                });
                mainButton.addEventListener("dragend", () => {
                    mainButton.classList.remove("is-dragging");
                });
            }

            mainButton.addEventListener("click", () => {
                const teacherId = Number(teacher.id);
                if (state.expandedTeachers.has(teacherId)) {
                    state.expandedTeachers.delete(teacherId);
                } else {
                    state.expandedTeachers.add(teacherId);
                }
                renderTeachersPanel();
            });

            container.append(item);
        });
}

function getDirectoryItems(type) {
    return state[type] || [];
}

function getDirectoryTitle(type, item) {
    if (type === "teachers") {
        return item.full_name;
    }
    return item.name;
}

function teacherSubjectNames(teacherId) {
    return state.teacher_subjects
        .filter((link) => Number(link.teacher_id) === Number(teacherId))
        .map((link) => state.subjects.find((subject) => Number(subject.id) === Number(link.subject_id)))
        .filter(Boolean)
        .map((subject) => subject.short_name || subject.name);
}

function filterDirectoryItems(type, items) {
    const query = state.directorySearch.toLowerCase().trim();
    if (!query) {
        return items;
    }

    return items.filter((item) => {
        const haystack = [
            item.name,
            item.full_name,
            item.short_name,
            item.speciality,
            item.course,
            item.room_type,
            item.seats,
            ...(type === "teachers" ? teacherSubjectNames(item.id) : []),
        ]
            .filter((value) => value != null && value !== "")
            .join(" ")
            .toLowerCase();
        return haystack.includes(query);
    });
}

function renderDirectoryCell(type, column, item) {
    if (column.key === "color") {
        return `
            <span class="glpi-color">
                <span class="glpi-color-swatch" style="background:${esc(item.color || "#6366f1")}"></span>
                ${esc(item.color || "—")}
            </span>
        `;
    }
    if (column.key === "course") {
        return esc(item.course ? `${item.course}` : "—");
    }
    if (column.key === "seats") {
        return esc(item.seats != null ? item.seats : "—");
    }
    if (column.key === "subjects") {
        const names = teacherSubjectNames(item.id);
        if (!names.length) {
            return '<span class="glpi-muted">не назначены</span>';
        }
        return `<span class="glpi-tags">${names.map((name) => `<span class="glpi-tag">${esc(name)}</span>`).join("")}</span>`;
    }
    return esc(item[column.key] || "—");
}

function renderDirectoryTable() {
    const type = state.directory;
    const meta = DIRECTORY_META[type];
    if (!meta || !$("#directory-table")) {
        return;
    }

    $("#directory-breadcrumb").textContent = meta.title;
    $("#directory-heading").textContent = meta.title;
    $("#directory-description").textContent = meta.description;

    const importButton = $("#directory-import-button");
    if (importButton) {
        const importLabels = {
            groups: "Импорт Excel (Группы)",
            teachers: "Импорт Excel (Сотрудники)",
            classrooms: "Импорт Excel (Аудитории)",
        };
        const canImport = Boolean(importLabels[type]);
        importButton.classList.toggle("hidden", !canImport);
        if (canImport) {
            importButton.textContent = importLabels[type];
        }
    }

    const items = filterDirectoryItems(type, getDirectoryItems(type));
    const total = getDirectoryItems(type).length;
    $("#directory-total").textContent =
        items.length === total
            ? `${total} ${pluralRecords(total)}`
            : `${items.length} из ${total}`;

    const thead = $("#directory-thead");
    thead.innerHTML = `
        <tr>
            <th class="glpi-col-id">№</th>
            ${meta.columns.map((column) => `<th>${esc(column.label)}</th>`).join("")}
            <th class="glpi-col-actions">Действия</th>
        </tr>
    `;

    const tbody = $("#directory-tbody");
    const empty = $("#directory-empty");
    tbody.innerHTML = "";

    if (!items.length) {
        empty.classList.remove("hidden");
        empty.textContent = total
            ? "Ничего не найдено по запросу."
            : "Записей пока нет. Нажмите «Добавить».";
        return;
    }

    empty.classList.add("hidden");

    items.forEach((item, index) => {
        const tr = document.createElement("tr");
        tr.className = "glpi-row";
        tr.innerHTML = `
            <td class="glpi-col-id">${index + 1}</td>
            ${meta.columns
                .map((column) => `<td>${renderDirectoryCell(type, column, item)}</td>`)
                .join("")}
            <td class="glpi-col-actions">
                <div class="glpi-row-actions">
                    ${
                        type === "teachers"
                            ? '<button type="button" class="glpi-action manage-subjects" title="Дисциплины">Дисциплины</button>'
                            : ""
                    }
                    <button type="button" class="glpi-action edit-reference" title="Изменить">Изменить</button>
                    <button type="button" class="glpi-action glpi-action-danger delete-reference" title="Удалить">Удалить</button>
                </div>
            </td>
        `;

        tr.querySelector(".edit-reference").addEventListener("click", (event) => {
            event.stopPropagation();
            openDirectory(type, item);
        });

        tr.querySelector(".delete-reference").addEventListener("click", async (event) => {
            event.stopPropagation();
            const title = getDirectoryTitle(type, item);
            const warning =
                type === "classrooms"
                    ? `Удалить аудиторию «${title}»? У занятий аудитория будет снята.`
                    : `Удалить «${title}»? Связанные занятия в расписании тоже будут удалены.`;

            if (!(await confirmDialog(warning, "Удаление"))) {
                return;
            }

            try {
                const result = await api(`/api/${type}/${item.id}`, { method: "DELETE" });
                const removed = Number(result.removed_lessons || 0);
                toast(
                    removed > 0
                        ? `Запись удалена. Также удалено занятий: ${removed}.`
                        : "Запись удалена.",
                );
                await loadData();
            } catch (error) {
                toast(error.message, "error");
            }
        });

        const subjectsButton = tr.querySelector(".manage-subjects");
        if (subjectsButton) {
            subjectsButton.addEventListener("click", (event) => {
                event.stopPropagation();
                openTeacherSubjects(item);
            });
        }

        tr.addEventListener("dblclick", () => openDirectory(type, item));
        tbody.append(tr);
    });
}

function pluralRecords(count) {
    const mod10 = count % 10;
    const mod100 = count % 100;
    if (mod10 === 1 && mod100 !== 11) {
        return "запись";
    }
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
        return "записи";
    }
    return "записей";
}

function openTeacherSubjects(teacher) {
    if (!isAdmin()) {
        return;
    }

    $("#teacher-subjects-title").textContent = teacher.full_name;
    $("#teacher-subjects-teacher-id").value = teacher.id;

    const assigned = new Set(
        state.teacher_subjects
            .filter((link) => Number(link.teacher_id) === Number(teacher.id))
            .map((link) => Number(link.subject_id)),
    );

    const fields = $("#teacher-subjects-fields");
    fields.innerHTML = state.subjects.length
        ? state.subjects.map((subject) => `
            <label class="checkbox-row">
                <input type="checkbox" value="${subject.id}" ${assigned.has(Number(subject.id)) ? "checked" : ""}>
                <span>${esc(subject.name)}</span>
            </label>
        `).join("")
        : '<div class="empty">Сначала добавьте дисциплины.</div>';

    $("#teacher-subjects-dialog").showModal();
}

async function saveTeacherSubjects(event) {
    event.preventDefault();

    if (!isAdmin()) {
        return;
    }

    const teacherId = Number($("#teacher-subjects-teacher-id").value);
    const subjectIds = [...document.querySelectorAll("#teacher-subjects-fields input:checked")]
        .map((input) => Number(input.value));

    try {
        await api(`/api/teachers/${teacherId}/subjects`, {
            method: "PUT",
            body: JSON.stringify({ subject_ids: subjectIds }),
        });
        $("#teacher-subjects-dialog").close();
        toast("Дисциплины преподавателя сохранены.");
        await loadData();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function importDirectory(type, { pickFile = false } = {}) {
    if (!isAdmin()) {
        toast("Импортировать справочники может только администратор.", "error");
        return;
    }

    const fileLabels = {
        groups: "Группы.xlsx",
        teachers: "Сотрудники.xlsx",
        classrooms: "Перечень аудиторий.xlsx",
    };
    if (!fileLabels[type]) {
        toast("Импорт Excel для этого справочника не поддерживается.", "error");
        return;
    }

    if (pickFile) {
        const input = $("#directory-import-file");
        if (!input) {
            return;
        }
        input.dataset.importType = type;
        input.click();
        return;
    }

    const fileLabel = fileLabels[type];
    const message =
        `Импортировать данные из файла «${fileLabel}» в папке проекта? ` +
        "Существующие записи с тем же названием будут обновлены. " +
        "Чтобы выбрать другой файл, зажмите Shift и нажмите кнопку импорта.";

    if (!(await confirmDialog(message, "Импорт Excel", "Импорт"))) {
        return;
    }

    await runDirectoryImport(type, null);
}

async function runDirectoryImport(type, file) {
    try {
        let result;
        if (file) {
            const formData = new FormData();
            formData.append("file", file);
            result = await apiUpload(`/api/${type}/import`, formData);
        } else {
            result = await api(`/api/${type}/import`, { method: "POST", body: "{}" });
        }

        const parts = [];
        if (result.created) {
            parts.push(`добавлено: ${result.created}`);
        }
        if (result.updated) {
            parts.push(`обновлено: ${result.updated}`);
        }
        toast(
            parts.length
                ? `Импорт «${result.source || "Excel"}»: ${parts.join(", ")}.`
                : `Импорт завершён (${result.total || 0} записей).`,
        );
        await loadData();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function clearDirectory(type) {
    if (!isAdmin()) {
        toast("Очищать справочники может только администратор.", "error");
        return;
    }

    const meta = DIRECTORY_META[type];
    if (!meta) {
        return;
    }

    const total = getDirectoryItems(type).length;
    if (!total) {
        toast("Справочник уже пуст.", "error");
        return;
    }

    const warning =
        type === "classrooms"
            ? `Удалить все аудитории (${total})? У занятий аудитория будет снята.`
            : `Удалить все записи справочника «${meta.title}» (${total})? ` +
              "Связанные занятия в расписании тоже будут удалены.";

    if (!(await confirmDialog(warning, "Удалить все"))) {
        return;
    }

    try {
        const result = await api(`/api/${type}/all`, { method: "DELETE" });
        const removed = Number(result.removed_lessons || 0);
        toast(
            removed > 0
                ? `Справочник очищен (${result.removed_items}). Также удалено занятий: ${removed}.`
                : `Справочник очищен (${result.removed_items} ${pluralRecords(result.removed_items)}).`,
        );
        await loadData();
    } catch (error) {
        toast(error.message, "error");
    }
}

function openDirectory(type, item = null) {
    if (!isAdmin()) {
        return;
    }

    const createTitles = {
        groups: "Новая учебная группа",
        teachers: "Новый преподаватель",
        subjects: "Новая дисциплина",
        classrooms: "Новая аудитория",
    };
    const editTitles = {
        groups: "Редактировать группу",
        teachers: "Редактировать преподавателя",
        subjects: "Редактировать дисциплину",
        classrooms: "Редактировать аудиторию",
    };

    $("#directory-type").value = type;
    $("#directory-id").value = item?.id || "";
    $("#directory-title").textContent = item ? editTitles[type] : createTitles[type];
    $("#directory-submit").textContent = item ? "Сохранить" : "Добавить";
    $("#directory-error").textContent = "";
    $("#directory-error").classList.add("hidden");

    const fields = $("#directory-fields");

    if (type === "teachers") {
        fields.innerHTML = `
            <div class="glpi-form-grid">
                <label class="glpi-field glpi-field-full">
                    <span>ФИО <em>*</em></span>
                    <input id="ref-full" required autofocus value="${esc(item?.full_name || "")}" placeholder="Иванов Сергей Владимирович">
                </label>
                <label class="glpi-field">
                    <span>Сокращение</span>
                    <input id="ref-short" value="${esc(item?.short_name || "")}" placeholder="Автоматически из ФИО">
                </label>
                <label class="glpi-field">
                    <span>Цвет карточки</span>
                    <input id="ref-color" type="color" value="${esc(item?.color || "#4f46e5")}">
                </label>
            </div>
        `;
    } else if (type === "subjects") {
        fields.innerHTML = `
            <div class="glpi-form-grid">
                <label class="glpi-field glpi-field-full">
                    <span>Название <em>*</em></span>
                    <input id="ref-name" required autofocus value="${esc(item?.name || "")}">
                </label>
                <label class="glpi-field">
                    <span>Краткое название</span>
                    <input id="ref-short" value="${esc(item?.short_name || "")}" placeholder="ОАП">
                </label>
                <label class="glpi-field">
                    <span>Цвет</span>
                    <input id="ref-color" type="color" value="${esc(item?.color || "#6366f1")}">
                </label>
            </div>
        `;
    } else if (type === "groups") {
        fields.innerHTML = `
            <div class="glpi-form-grid">
                <label class="glpi-field">
                    <span>Название группы <em>*</em></span>
                    <input id="ref-name" required autofocus value="${esc(item?.name || "")}" placeholder="П-21">
                </label>
                <label class="glpi-field">
                    <span>Курс</span>
                    <input id="ref-course" type="number" min="1" max="6" value="${esc(item?.course || 1)}">
                </label>
                <label class="glpi-field glpi-field-full">
                    <span>Специальность</span>
                    <input id="ref-speciality" value="${esc(item?.speciality || "")}" placeholder="Программирование">
                </label>
            </div>
        `;
    } else {
        fields.innerHTML = `
            <div class="glpi-form-grid">
                <label class="glpi-field">
                    <span>Номер аудитории <em>*</em></span>
                    <input id="ref-name" required autofocus value="${esc(item?.name || "")}" placeholder="305">
                </label>
                <label class="glpi-field">
                    <span>Мест</span>
                    <input id="ref-seats" type="number" min="0" value="${esc(item?.seats ?? "")}">
                </label>
                <label class="glpi-field glpi-field-full">
                    <span>Тип</span>
                    <input id="ref-room-type" value="${esc(item?.room_type || "")}" placeholder="лаборатория / лекционная">
                </label>
            </div>
        `;
    }

    $("#directory-dialog").showModal();
}

async function saveDirectory(event) {
    event.preventDefault();

    const errorNode = $("#directory-error");
    const showDirectoryError = (message) => {
        errorNode.textContent = message;
        errorNode.classList.remove("hidden");
    };

    const clearDirectoryError = () => {
        errorNode.textContent = "";
        errorNode.classList.add("hidden");
    };

    clearDirectoryError();

    if (!isAdmin()) {
        showDirectoryError("Только администратор может изменять справочники.");
        return;
    }

    const type = $("#directory-type").value;
    const id = $("#directory-id").value;
    let data = {};

    if (type === "teachers") {
        data = {
            full_name: $("#ref-full").value.trim(),
            short_name: $("#ref-short").value.trim(),
            color: $("#ref-color").value,
        };
    } else if (type === "subjects") {
        data = {
            name: $("#ref-name").value.trim(),
            short_name: $("#ref-short").value.trim(),
            color: $("#ref-color").value,
        };
    } else if (type === "groups") {
        data = {
            name: $("#ref-name").value.trim(),
            speciality: $("#ref-speciality").value.trim(),
            course: Number($("#ref-course").value || 1),
        };
    } else {
        data = {
            name: $("#ref-name").value.trim(),
            room_type: $("#ref-room-type").value.trim(),
            seats: $("#ref-seats").value === "" ? null : Number($("#ref-seats").value),
        };
    }

    const empty = type === "teachers" ? !data.full_name : !data.name;
    if (empty) {
        showDirectoryError("Заполните обязательные поля.");
        return;
    }

    try {
        await api(id ? `/api/${type}/${id}` : `/api/${type}`, {
            method: id ? "PUT" : "POST",
            body: JSON.stringify(data),
        });

        $("#directory-dialog").close();
        toast(id ? "Запись обновлена." : "Запись добавлена.");
        await loadData();
        if (state.view !== "directory") {
            switchView("directory", type);
        } else {
            state.directory = type;
            renderDirectoryTable();
        }
    } catch (error) {
        showDirectoryError(error.message);
    }
}

function openPrintGroup() {
    if (!state.groups.length) {
        toast("Сначала добавьте учебную группу.", "error");
        return;
    }

    const groupId = state.group || state.groups[0].id;
    window.open(`/print/${groupId}`, "_blank");
}

function openPrintAll() {
    if (!state.groups.length) {
        toast("Сначала добавьте учебные группы.", "error");
        return;
    }

    window.open("/print/all", "_blank");
}

async function copyWeek(event) {
    event.preventDefault();

    if (!isAdmin()) {
        toast("Копировать расписание может только администратор.", "error");
        return;
    }

    const sourceWeek = Number($("#copy-source-week").value);
    const targetWeek = Number($("#copy-target-week").value);

    if (sourceWeek === targetWeek) {
        toast("Выберите разные недели.", "error");
        return;
    }

    try {
        const result = await api("/api/lessons/copy-week", {
            method: "POST",
            body: JSON.stringify({
                source_week: sourceWeek,
                target_week: targetWeek,
            }),
        });

        $("#copy-week-dialog").close();
        const removed = Number(result.removed || 0);
        toast(
            removed > 0
                ? `Неделя перезаписана: скопировано ${result.copied}, удалено старых ${removed}.`
                : `Скопировано занятий: ${result.copied}.`,
        );

        state.week = targetWeek;
        updateWeekButtons();
        await loadLessons();
        render();
    } catch (error) {
        toast(error.message, "error");
    }
}

function updateWeekButtons() {
    document.querySelectorAll(".week-button").forEach((button) => {
        button.classList.toggle(
            "active",
            Number(button.dataset.week) === state.week,
        );
    });

    $("#current-week-label").textContent = `${state.week}-я неделя`;
}

function setup() {
    setupScheduleEdgeScroll();

    $("#login-form").addEventListener("submit", login);

    $("#logout-button").addEventListener("click", logout);

    $("#directories-toggle")?.addEventListener("click", () => {
        const open = $("#directories-toggle").getAttribute("aria-expanded") !== "true";
        setDirectoriesOpen(open);
    });

    $("#add-lesson-button").addEventListener("click", () => {
        if (isAdmin()) {
            openLesson();
        }
    });

    $("#print-all-button").addEventListener("click", openPrintAll);
    $("#print-group-button").addEventListener("click", openPrintGroup);

    $("#copy-week-button").addEventListener("click", () => {
        if (!isAdmin()) {
            return;
        }

        $("#copy-source-week").value = String(state.week);
        $("#copy-target-week").value = state.week === 1 ? "2" : "1";
        $("#copy-week-dialog").showModal();
    });

    $("#copy-week-form").addEventListener("submit", copyWeek);

    $("#lesson-form").addEventListener("submit", saveLesson);
    $("#lesson-teacher").addEventListener("change", () => updateLessonSubjects(null, true));
    $("#lesson-split")?.addEventListener("change", (event) => {
        setLessonSplitMode(event.target.checked);
    });
    $("#delete-lesson-button").addEventListener("click", deleteCurrentLesson);

    $("#schedule-groups-list")?.addEventListener("change", (event) => {
        state.group = event.target.value;
        render();
    });

    $("#search-input").addEventListener("input", (event) => {
        state.search = event.target.value;
        renderSchedule();
    });

    $("#teacher-search").addEventListener("input", renderTeachersPanel);

    document.querySelectorAll(".week-button").forEach((button) => {
        button.addEventListener("click", async () => {
            state.week = Number(button.dataset.week);
            updateWeekButtons();
            await loadLessons();
            render();
        });
    });

    document.querySelectorAll("[data-close]").forEach((button) => {
        button.addEventListener("click", () => {
            button.closest("dialog").close();
        });
    });

    $("#directory-add-button").addEventListener("click", () => {
        openDirectory(state.directory);
    });

    $("#directory-import-button")?.addEventListener("click", (event) => {
        importDirectory(state.directory, { pickFile: event.shiftKey });
    });

    $("#directory-import-file")?.addEventListener("change", async (event) => {
        const input = event.target;
        const file = input.files?.[0];
        const type = input.dataset.importType;
        input.value = "";
        if (!file || !type) {
            return;
        }
        await runDirectoryImport(type, file);
    });

    $("#directory-clear-button")?.addEventListener("click", () => {
        clearDirectory(state.directory);
    });

    $("#directory-search").addEventListener("input", (event) => {
        state.directorySearch = event.target.value;
        renderDirectoryTable();
    });

    $("#directory-form").addEventListener("submit", saveDirectory);
    $("#teacher-subjects-form").addEventListener("submit", saveTeacherSubjects);

    document.querySelectorAll("[data-view]").forEach((control) => {
        control.addEventListener("click", () => {
            switchView(control.dataset.view, control.dataset.directory || null);
        });
    });

    updateWeekButtons();
}

async function start() {
    setup();

    try {
        const me = await api("/api/auth/me");

        if (me.authenticated) {
            state.user = me;
            showApp();
            await loadData();
        }
    } catch (error) {
        console.error(error);
    }
}

document.addEventListener("DOMContentLoaded", start);

