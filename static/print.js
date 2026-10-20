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

function lessonCellHtml(lesson) {
    if (!lesson) {
        return '<td class="empty-cell"></td>';
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
            <div class="cell-teacher">${esc(teacher)}</div>
            <div class="cell-subject">${esc(subject)}</div>
            ${room}
        </td>
    `;
}

function buildBoardTable(groups, lessons, week, weekLabel) {
    const wrapper = document.createElement("div");
    wrapper.className = "print-board-wrap";

    const title = document.createElement("div");
    title.className = "week-title";
    title.textContent = weekLabel;
    wrapper.append(title);

    if (!groups.length) {
        wrapper.innerHTML += '<p class="empty">Групп нет</p>';
        return wrapper;
    }

    const table = document.createElement("table");
    table.className = "print-board";

    const head = `
        <thead>
            <tr>
                <th class="corner">День / пара</th>
                ${groups.map((group) => `<th>${esc(group.name)}</th>`).join("")}
            </tr>
        </thead>
    `;

    let body = "<tbody>";
    for (let weekday = 1; weekday <= 6; weekday += 1) {
        body += `
            <tr class="day-row">
                <td class="day-label" colspan="${groups.length + 1}">${esc(DAYS[weekday - 1])}</td>
            </tr>
        `;

        for (let period = 1; period <= 4; period += 1) {
            body += `<tr><td class="pair-label">${period}</td>`;
            groups.forEach((group) => {
                const lesson = lessons.find(
                    (item) =>
                        Number(item.week) === week &&
                        Number(item.weekday) === weekday &&
                        Number(item.period) === period &&
                        Number(item.group_id) === Number(group.id),
                );
                body += lessonCellHtml(lesson);
            });
            body += "</tr>";
        }
    }
    body += "</tbody>";

    table.innerHTML = head + body;
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
    table.innerHTML = "<thead><tr><th>День</th><th>Пара</th><th>Занятие</th></tr></thead>";

    const tbody = document.createElement("tbody");
    const weekLessons = lessons
        .filter((lesson) => Number(lesson.week) === week)
        .sort((a, b) => a.weekday - b.weekday || a.period - b.period);

    if (!weekLessons.length) {
        tbody.innerHTML = '<tr><td colspan="3" class="empty">Занятий нет</td></tr>';
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
                <td>
                    <strong>${esc(lesson.subject_name)}</strong>
                    — ${esc(teacher)}${esc(roomText)}
                </td>
            `;
            tbody.append(tr);
        });
    }

    table.append(tbody);
    wrapper.append(table);
    return wrapper;
}

async function init() {
    document.getElementById("print-button").addEventListener("click", () => window.print());

    const header = document.getElementById("print-header");
    const container = document.getElementById("print-tables");

    if (mode === "all") {
        const [bootstrap, lessons] = await Promise.all([
            api("/api/bootstrap"),
            api("/api/lessons"),
        ]);

        header.innerHTML = `
            <h1>Расписание занятий</h1>
            <p>Все группы · 1-я и 2-я учебные недели</p>
        `;
        document.title = "Расписание — все группы";

        const groups = bootstrap.groups || [];
        container.append(buildBoardTable(groups, lessons, 1, "1-я учебная неделя"));
        container.append(buildBoardTable(groups, lessons, 2, "2-я учебная неделя"));
        return;
    }

    const [bootstrap, lessons] = await Promise.all([
        api("/api/bootstrap"),
        api(`/api/lessons?group_id=${groupId}`),
    ]);

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
