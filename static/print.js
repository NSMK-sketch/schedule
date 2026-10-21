const DAYS = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
];

const script = document.currentScript;
const mode = script.dataset.mode || "group";
const groupId = script.dataset.groupId ? Number(script.dataset.groupId) : null;

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    })[char]);
}

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

async function api(url) {
    const response = await fetch(url, { credentials: "same-origin" });
    if (response.status === 401) {
        window.location.href = "/";
        throw new Error("Требуется авторизация.");
    }
    const data = await response.json();
    if (!response.ok) {
        throw new Error(data.error || "Ошибка загрузки.");
    }
    return data;
}

function getPrintFilters() {
    const params = new URLSearchParams(window.location.search);
    const teacherId = params.get("teacher_id");
    const subjectId = params.get("subject_id");
    const query = (params.get("q") || "").trim();
    return {
        teacherId: teacherId || "",
        subjectId: subjectId || "",
        query,
        active: Boolean(teacherId || subjectId || query),
    };
}

function lessonCellHtml(lesson, { compactEmpty = false } = {}) {
    if (!lesson) {
        return `<td class="empty-cell${compactEmpty ? " empty-cell-compact" : ""}"></td>`;
    }

    const teacher1 =
        formatTeacherSurnameInitials(lesson.teacher_name) || lesson.teacher_short || "";
    const teacher2 = lesson.teacher2_id
        ? formatTeacherSurnameInitials(lesson.teacher2_name) || lesson.teacher2_short || ""
        : "";
    const teacher = teacher2 ? `${teacher1} / ${teacher2}` : teacher1;
    const subject = lesson.subject_name || "Предмет не назначен";
    const rooms = [
        lesson.classroom_name || null,
        lesson.teacher2_id ? lesson.classroom2_name || null : null,
    ].filter(Boolean);
    const room = rooms.length
        ? `<div class="cell-room">ауд. ${esc(rooms.join(" / "))}</div>`
        : "";

    return `
        <td class="lesson-cell${lesson.subject_id ? "" : " pending-cell"}${
            lesson.teacher2_id ? " split-cell" : ""
        }">
            <div class="cell-subject">${esc(subject)}</div>
            <div class="cell-teacher">${esc(teacher)}</div>
            ${room}
        </td>
    `;
}

function buildBoardTable(groups, lessons, week, weekLabel, { compact = false } = {}) {
    const wrapper = document.createElement("div");
    wrapper.className = `print-board-wrap${compact ? " is-filtered" : ""}`;

    const title = document.createElement("div");
    title.className = "week-title";
    title.textContent = weekLabel;
    wrapper.append(title);

    const weekLessons = lessons.filter((lesson) => Number(lesson.week) === week);
    const activeGroups = compact
        ? groups.filter((group) =>
              weekLessons.some(
                  (lesson) => Number(lesson.group_id) === Number(group.id),
              ),
          )
        : groups;

    if (!activeGroups.length) {
        wrapper.innerHTML += '<p class="empty">Занятий нет</p>';
        return wrapper;
    }

    const index = new Map();
    weekLessons.forEach((lesson) => {
        index.set(
            `${lesson.weekday}-${lesson.period}-${lesson.group_id}`,
            lesson,
        );
    });

    const table = document.createElement("table");
    table.className = `print-board${compact ? " print-board-filtered" : ""}`;

    let body = "<tbody>";
    let anyRow = false;

    for (let weekday = 1; weekday <= 6; weekday += 1) {
        const periods = [];
        for (let period = 1; period <= 4; period += 1) {
            const hasLesson = activeGroups.some((group) =>
                index.has(`${weekday}-${period}-${group.id}`),
            );
            if (!compact || hasLesson) {
                periods.push(period);
            }
        }
        if (!periods.length) {
            continue;
        }

        anyRow = true;
        body += `
            <tr class="day-row">
                <td class="day-label" colspan="${activeGroups.length + 1}">${esc(DAYS[weekday - 1])}</td>
            </tr>
        `;

        periods.forEach((period) => {
            body += `<tr><td class="pair-label">${period}</td>`;
            activeGroups.forEach((group) => {
                const lesson = index.get(`${weekday}-${period}-${group.id}`) || null;
                body += lessonCellHtml(lesson, { compactEmpty: compact });
            });
            body += "</tr>";
        });
    }
    body += "</tbody>";

    if (!anyRow) {
        wrapper.innerHTML += '<p class="empty">Занятий нет</p>';
        return wrapper;
    }

    table.innerHTML = `
        <thead>
            <tr>
                <th class="corner">Пара</th>
                ${activeGroups.map((group) => `<th>${esc(group.name)}</th>`).join("")}
            </tr>
        </thead>
        ${body}
    `;
    wrapper.append(table);
    return wrapper;
}

function buildGroupListTable(lessons, week, weekLabel) {
    const wrapper = document.createElement("div");
    const title = document.createElement("div");
    title.className = "week-title";
    title.textContent = weekLabel;
    wrapper.append(title);

    const table = document.createElement("table");
    table.className = "print-grid";
    table.innerHTML =
        "<thead><tr><th>День</th><th>Пара</th><th>Группа</th><th>Занятие</th></tr></thead>";

    const tbody = document.createElement("tbody");
    const weekLessons = lessons
        .filter((lesson) => Number(lesson.week) === week)
        .sort(
            (a, b) =>
                a.weekday - b.weekday ||
                a.period - b.period ||
                String(a.group_name || "").localeCompare(String(b.group_name || ""), "ru"),
        );

    if (!weekLessons.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty">Занятий нет</td></tr>';
    } else {
        weekLessons.forEach((lesson) => {
            const teacher1 =
                formatTeacherSurnameInitials(lesson.teacher_name) ||
                lesson.teacher_name ||
                "";
            const teacher2 = lesson.teacher2_id
                ? formatTeacherSurnameInitials(lesson.teacher2_name) ||
                  lesson.teacher2_name ||
                  ""
                : "";
            const teacher = teacher2 ? `${teacher1} / ${teacher2}` : teacher1;
            const rooms = [
                lesson.classroom_name || null,
                lesson.teacher2_id ? lesson.classroom2_name || null : null,
            ].filter(Boolean);
            const roomText = rooms.length ? `, ауд. ${rooms.join(" / ")}` : "";
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td class="day-cell">${esc(DAYS[lesson.weekday - 1] || lesson.weekday)}</td>
                <td class="pair-cell">${esc(lesson.period)}</td>
                <td>${esc(lesson.group_name || "")}</td>
                <td>
                    <div class="cell-subject">${esc(lesson.subject_name || "")}</div>
                    <div class="cell-teacher">${esc(teacher)}${esc(roomText)}</div>
                </td>
            `;
            tbody.append(tr);
        });
    }

    table.append(tbody);
    wrapper.append(table);
    return wrapper;
}

function parseGroupIdsFromQuery() {
    const raw = new URLSearchParams(window.location.search).get("groups");
    if (!raw) {
        return null;
    }
    const ids = raw
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isFinite(value) && value > 0);
    return ids.length ? ids : null;
}

function filterGroupsByIds(groups, ids) {
    if (!ids) {
        return groups;
    }
    const wanted = new Set(ids.map(Number));
    return groups.filter((group) => wanted.has(Number(group.id)));
}

function filterLessonsByQuery(lessons, filters) {
    const teacherId = filters.teacherId;
    const subjectId = filters.subjectId;
    const query = filters.query.toLowerCase();

    return lessons.filter((lesson) => {
        if (teacherId) {
            const tid = String(teacherId);
            if (
                String(lesson.teacher_id ?? "") !== tid &&
                String(lesson.teacher2_id ?? "") !== tid
            ) {
                return false;
            }
        }
        if (subjectId && String(lesson.subject_id ?? "") !== String(subjectId)) {
            return false;
        }
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
}

function groupsWithLessons(groups, lessons) {
    const ids = new Set(lessons.map((lesson) => Number(lesson.group_id)));
    return groups.filter((group) => ids.has(Number(group.id)));
}

function buildFilterMeta(filters, bootstrap, groups) {
    const tags = [];

    if (groups.length === 1) {
        tags.push(`Группа ${groups[0].name}`);
    } else if (groups.length) {
        tags.push(`${groups.length} групп`);
    }

    if (filters.teacherId) {
        const teacher = (bootstrap.teachers || []).find(
            (item) => String(item.id) === String(filters.teacherId),
        );
        tags.push(
            teacher
                ? `Преподаватель: ${formatTeacherSurnameInitials(teacher.full_name) || teacher.full_name}`
                : "Преподаватель",
        );
    }

    if (filters.subjectId) {
        const subject = (bootstrap.subjects || []).find(
            (item) => String(item.id) === String(filters.subjectId),
        );
        tags.push(subject ? `Предмет: ${subject.name}` : "Предмет");
    }

    if (filters.query) {
        tags.push(`Поиск: ${filters.query}`);
    }

    tags.push("1-я и 2-я недели");
    return tags;
}

async function init() {
    document.getElementById("print-button").addEventListener("click", () => window.print());

    const header = document.getElementById("print-header");
    const container = document.getElementById("print-tables");
    const filters = getPrintFilters();

    if (mode === "all") {
        const groupIds = parseGroupIdsFromQuery();
        const [bootstrap, allLessons] = await Promise.all([
            api("/api/bootstrap"),
            api("/api/lessons"),
        ]);

        let lessons = filterLessonsByQuery(allLessons, filters);
        let groups = filterGroupsByIds(bootstrap.groups || [], groupIds);

        if (filters.active) {
            groups = groupsWithLessons(groups, lessons);
            lessons = lessons.filter((lesson) =>
                groups.some((group) => Number(group.id) === Number(lesson.group_id)),
            );
        }

        if (!groups.length || !lessons.length) {
            header.innerHTML = "<p>Нет занятий по выбранным фильтрам.</p>";
            return;
        }

        const tags = buildFilterMeta(filters, bootstrap, groups);
        header.innerHTML = `
            <h1>Расписание занятий</h1>
            <div class="filter-tags">
                ${tags.map((tag) => `<span class="filter-tag">${esc(tag)}</span>`).join("")}
            </div>
        `;
        document.title =
            groups.length === 1
                ? `Расписание ${groups[0].name}`
                : `Расписание — ${groups.length} групп`;

        // Фильтры / мало групп — без пустых строк и колонок
        const compact = filters.active || groups.length <= 6;

        container.append(
            buildBoardTable(groups, lessons, 1, "1-я учебная неделя", { compact }),
        );
        container.append(
            buildBoardTable(groups, lessons, 2, "2-я учебная неделя", { compact }),
        );
        return;
    }

    const [bootstrap, rawLessons] = await Promise.all([
        api("/api/bootstrap"),
        api(`/api/lessons?group_id=${groupId}`),
    ]);

    const lessons = filterLessonsByQuery(rawLessons, filters);
    const group = bootstrap.groups.find((item) => Number(item.id) === groupId);
    if (!group) {
        header.innerHTML = "<p>Группа не найдена</p>";
        return;
    }

    const meta = [
        group.speciality || null,
        group.course ? `${group.course} курс` : null,
    ]
        .filter(Boolean)
        .join(", ");

    header.innerHTML = `
        <h1>Расписание группы ${esc(group.name)}</h1>
        ${meta ? `<p>${esc(meta)}</p>` : ""}
    `;
    document.title = `Расписание ${group.name}`;

    container.append(buildGroupListTable(lessons, 1, "1-я учебная неделя"));
    container.append(buildGroupListTable(lessons, 2, "2-я учебная неделя"));
}

init().catch((error) => {
    console.error(error);
    document.getElementById("print-header").innerHTML =
        `<p>Ошибка загрузки данных: ${esc(error.message)}</p>`;
});
