const WEEKDAYS = [
    "",
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
];

const state = {
    sheets: [],
    current: null,
    groups: [],
    subjects: [],
    teachers: [],
    chatId: "",
    dirty: false,
};

const $ = (selector) => document.querySelector(selector);

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
    })[char]);
}

async function api(url, options = {}) {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || "Не удалось выполнить запрос.");
    }
    return data;
}

function showNotice(text, kind) {
    const node = $("#notice");
    node.textContent = text || "";
    node.className = text ? `notice ${kind || ""}` : "notice hidden";
}

function schoolTodayIso() {
    const shifted = new Date(Date.now() + 7 * 60 * 60 * 1000);
    const month = String(shifted.getUTCMonth() + 1).padStart(2, "0");
    const day = String(shifted.getUTCDate()).padStart(2, "0");
    return `${shifted.getUTCFullYear()}-${month}-${day}`;
}

function addDays(iso, days) {
    const [year, month, day] = iso.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    date.setUTCDate(date.getUTCDate() + days);
    const nextMonth = String(date.getUTCMonth() + 1).padStart(2, "0");
    const nextDay = String(date.getUTCDate()).padStart(2, "0");
    return `${date.getUTCFullYear()}-${nextMonth}-${nextDay}`;
}

function weekdayOf(iso) {
    const [year, month, day] = iso.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    const sundayFirst = date.getUTCDay();
    return sundayFirst === 0 ? 7 : sundayFirst;
}

function defaultDate() {
    let iso = schoolTodayIso();
    if (weekdayOf(iso) === 7) {
        iso = addDays(iso, 1);
    }
    return iso;
}

function paperTeacher(fullName) {
    const parts = String(fullName || "").trim().split(/\s+/).filter(Boolean);
    if (parts.length < 2) {
        return parts[0] || "";
    }
    const initials = parts.slice(1).map((part) => part[0].toUpperCase()).join("");
    return `${parts[0]}${initials}`;
}

function fillLists() {
    const subjects = $("#subject-options");
    subjects.innerHTML = state.subjects
        .map((item) => `<option value="${esc(item.name)}"></option>`)
        .join("");
    const teachers = $("#teacher-options");
    const names = new Set();
    state.teachers.forEach((teacher) => {
        [paperTeacher(teacher.full_name), teacher.short_name, teacher.full_name]
            .filter(Boolean)
            .forEach((name) => names.add(name));
    });
    teachers.innerHTML = [...names]
        .map((name) => `<option value="${esc(name)}"></option>`)
        .join("");
}

function groupOptions(selectedId) {
    const byCourse = new Map();
    state.groups.forEach((group) => {
        const course = Number(group.course) || 1;
        if (!byCourse.has(course)) {
            byCourse.set(course, []);
        }
        byCourse.get(course).push(group);
    });
    const groups = [...byCourse.keys()]
        .sort((a, b) => a - b)
        .map((course) => {
            const options = byCourse
                .get(course)
                .slice()
                .sort((a, b) => String(a.name).localeCompare(String(b.name), "ru"))
                .map((group) => {
                    const selected = String(group.id) === String(selectedId) ? " selected" : "";
                    return `<option value="${group.id}"${selected}>${esc(group.name)}</option>`;
                })
                .join("");
            return `<optgroup label="${course} курс">${options}</optgroup>`;
        })
        .join("");
    return `<option value="">Группа…</option>${groups}`;
}

function blankRow() {
    return {
        group_id: "",
        periods_label: "",
        new_subject: "",
        new_room: "",
        new_teacher: "",
        old_subject: "",
        absent_teacher: "",
    };
}

function renderList() {
    const root = $("#sheet-list");
    if (!state.sheets.length) {
        root.innerHTML = `<p class="hint">Листов пока нет.</p>`;
        return;
    }
    root.innerHTML = state.sheets
        .map((sheet) => {
            const active = state.current && Number(state.current.id) === Number(sheet.id);
            const status = sheet.status === "published" ? "Опубликовано" : "Черновик";
            return `
                <button type="button" class="sheet-card${active ? " active" : ""}" data-open="${sheet.id}">
                    <b>${esc(sheet.date_label)}</b>
                    <span>${esc(sheet.weekday_label)}, ${sheet.week}-я неделя · ${sheet.row_count} стр.</span>
                    <span class="status${sheet.status === "published" ? " status-published" : ""}">${status}</span>
                </button>
            `;
        })
        .join("");
}

function rowHtml(row, locked) {
    const disabled = locked ? " disabled" : "";
    return `
        <tr>
            <td>
                <select data-field="group_id"${disabled}>${groupOptions(row.group_id || "")}</select>
            </td>
            <td class="period">
                <input data-field="periods" value="${esc(row.periods_label || "")}" placeholder="3,4"${disabled}>
            </td>
            <td>
                <input data-field="new_subject" list="subject-options" value="${esc(row.new_subject || "")}"${disabled}>
            </td>
            <td class="room">
                <input data-field="new_room" value="${esc(row.new_room || "")}" placeholder="407"${disabled}>
            </td>
            <td>
                <input data-field="new_teacher" list="teacher-options" value="${esc(row.new_teacher || "")}"${disabled}>
            </td>
            <td>
                <input data-field="old_subject" list="subject-options" value="${esc(row.old_subject || "")}"${disabled}>
            </td>
            <td>
                <input data-field="absent_teacher" list="teacher-options" value="${esc(row.absent_teacher || "")}"${disabled}>
            </td>
            <td class="row-actions">
                ${
                    locked
                        ? ""
                        : `<button type="button" class="icon-btn" data-move="up">↑</button>
                           <button type="button" class="icon-btn" data-move="down">↓</button>
                           <button type="button" class="icon-btn danger" data-remove-row>×</button>`
                }
            </td>
        </tr>
    `;
}

function previewTitle(date, week) {
    const weekday = weekdayOf(date);
    if (!date || weekday === 7) {
        return "Укажите учебный день";
    }
    const [year, month, day] = date.split("-");
    return `Замена на ${day}.${month}.${year}г ${week}-Я НЕДЕЛЯ (${WEEKDAYS[weekday].toUpperCase()})`;
}

function renderEditor() {
    const root = $("#editor");
    const sheet = state.current;
    if (!sheet) {
        root.innerHTML = `<div class="empty-editor">Создайте лист или выберите его слева. Черновик можно отложить и править до публикации.</div>`;
        return;
    }
    const locked = sheet.status === "published";
    const rows = (sheet.rows || []).slice();
    if (!locked && !rows.length) {
        rows.push(blankRow());
    }
    const date = sheet.sheet_date;
    const notify = sheet.last_notify_error
        ? `<p class="hint">Уведомление: ${esc(sheet.last_notify_error)}</p>`
        : sheet.last_notify_at
          ? `<p class="hint">Уведомление в MAX отправлено ${esc(sheet.last_notify_at)}.</p>`
          : "";
    root.innerHTML = `
        <section class="editor-card">
            <div class="editor-head">
                <label>
                    Дата
                    <input id="sheet-date" type="date" value="${esc(date)}"${locked ? " disabled" : ""}>
                </label>
                <div>
                    <div class="hint">Неделя</div>
                    <div class="week-switch">
                        <button type="button" class="week-pick${Number(sheet.week) === 1 ? " active" : ""}" data-week="1"${locked ? " disabled" : ""}>1-я</button>
                        <button type="button" class="week-pick${Number(sheet.week) === 2 ? " active" : ""}" data-week="2"${locked ? " disabled" : ""}>2-я</button>
                    </div>
                </div>
                <div>
                    <div class="hint">День</div>
                    <strong id="weekday-label">${esc(WEEKDAYS[weekdayOf(date)] || "воскресенье")}</strong>
                </div>
                <span class="status${locked ? " status-published" : ""}">${locked ? "Опубликовано" : "Черновик"}</span>
            </div>
            <p class="hint">Замена разовая: студенты видят её только на эту дату. На следующей неделе в этот день снова обычное расписание.</p>
            <div class="preview-title" id="preview-title">${esc(previewTitle(date, sheet.week))}</div>
            <div class="table-scroll">
                <table class="edit-table">
                    <colgroup>
                        <col class="c-group">
                        <col class="c-period">
                        <col class="c-subject">
                        <col class="c-room">
                        <col class="c-teacher">
                        <col class="c-subject">
                        <col class="c-teacher">
                        <col class="c-actions">
                    </colgroup>
                    <thead>
                        <tr>
                            <th rowspan="2">Группа</th>
                            <th rowspan="2">пара</th>
                            <th colspan="3">${esc(sheet.date_label)} — что будет</th>
                            <th colspan="2">Заменяемый предмет, отсутствующий</th>
                            <th rowspan="2"></th>
                        </tr>
                        <tr>
                            <th>Предмет</th>
                            <th>ауд.</th>
                            <th>Преподаватель</th>
                            <th>Предмет</th>
                            <th>Преподаватель</th>
                        </tr>
                    </thead>
                    <tbody id="change-rows">
                        ${rows.map((row) => rowHtml(row, locked)).join("")}
                    </tbody>
                </table>
            </div>
            <div class="editor-actions">
                ${locked ? "" : `<button type="button" id="add-row">+ Строка</button>`}
                ${locked ? "" : `<button type="button" id="save-sheet">Сохранить</button>`}
                ${
                    locked
                        ? `<button type="button" id="unpublish-sheet">Снять с публикации</button>
                           <button type="button" class="primary" id="notify-sheet">Отправить в MAX ещё раз</button>`
                        : `<button type="button" class="primary" id="publish-sheet">Опубликовать</button>`
                }
                <button type="button" class="danger" id="delete-sheet">Удалить</button>
            </div>
            ${notify}
        </section>
    `;
}

function render() {
    renderList();
    renderEditor();
}

function markDirty() {
    state.dirty = true;
}

function readSheetFromDom() {
    const sheet = state.current;
    const rows = [...document.querySelectorAll("#change-rows tr")].map((row) => {
        const group = row.querySelector("[data-field='group_id']");
        const option = group.selectedOptions[0];
        return {
            group_id: group.value,
            group_name: group.value ? option.textContent.trim() : "",
            periods: row.querySelector("[data-field='periods']").value,
            new_subject: row.querySelector("[data-field='new_subject']").value,
            new_room: row.querySelector("[data-field='new_room']").value,
            new_teacher: row.querySelector("[data-field='new_teacher']").value,
            old_subject: row.querySelector("[data-field='old_subject']").value,
            absent_teacher: row.querySelector("[data-field='absent_teacher']").value,
        };
    });
    return {
        sheet_date: $("#sheet-date").value,
        week: Number(sheet.week),
        rows,
    };
}

function rememberRowsLocally() {
    if (!state.current || state.current.status === "published") {
        return;
    }
    const payload = readSheetFromDom();
    state.current.sheet_date = payload.sheet_date;
    state.current.date_label = payload.sheet_date
        ? payload.sheet_date.split("-").reverse().join(".")
        : state.current.date_label;
    state.current.rows = payload.rows.map((row) => ({
        ...row,
        periods_label: row.periods,
    }));
}

async function refreshList() {
    state.sheets = await api("/api/substitutions");
}

async function openSheet(id) {
    if (state.dirty && !window.confirm("Есть несохранённые правки. Перейти без сохранения?")) {
        return;
    }
    state.current = await api(`/api/substitutions/${id}`);
    state.dirty = false;
    render();
}

async function saveSheet() {
    const payload = readSheetFromDom();
    if (weekdayOf(payload.sheet_date) === 7) {
        showNotice("На воскресенье замену создать нельзя.");
        return;
    }
    try {
        state.current = await api(`/api/substitutions/${state.current.id}`, {
            method: "PUT",
            body: JSON.stringify(payload),
        });
        state.dirty = false;
        await refreshList();
        render();
        showNotice("Черновик сохранён. Его можно изменить в любой момент до публикации.", "ok");
    } catch (error) {
        showNotice(error.message);
    }
}

async function publishSheet() {
    const label = state.current.date_label;
    const agreed = window.confirm(
        `Опубликовать замены на ${label}? Студенты увидят их только в эту дату, на следующей неделе снова будет обычное расписание. В MAX уйдёт сообщение со ссылкой на таблицу.`,
    );
    if (!agreed) {
        return;
    }
    try {
        if (state.dirty || state.current.status !== "published") {
            const payload = readSheetFromDom();
            state.current = await api(`/api/substitutions/${state.current.id}`, {
                method: "PUT",
                body: JSON.stringify(payload),
            });
            state.dirty = false;
        }
        const result = await api(`/api/substitutions/${state.current.id}/publish`, {
            method: "POST",
            body: "{}",
        });
        state.current = result.sheet;
        await refreshList();
        render();
        const notify = result.notify || {};
        if (notify.sent) {
            showNotice(notify.warning || "Опубликовано. Сообщение отправлено в MAX.", notify.warning ? "" : "ok");
        } else {
            showNotice(`Опубликовано. ${notify.error || "Уведомление не отправлено."}`);
        }
    } catch (error) {
        showNotice(error.message);
    }
}

function bindEditor() {
    $("#editor").addEventListener("input", (event) => {
        if (event.target.closest("#change-rows, #sheet-date")) {
            markDirty();
        }
    });
    $("#editor").addEventListener("change", (event) => {
        if (event.target.id === "sheet-date") {
            const weekday = $("#weekday-label");
            const name = WEEKDAYS[weekdayOf(event.target.value)] || "воскресенье";
            if (weekday) {
                weekday.textContent = name;
            }
            const title = $("#preview-title");
            if (title && state.current) {
                title.textContent = previewTitle(event.target.value, state.current.week);
            }
            markDirty();
        }
    });
    $("#editor").addEventListener("click", async (event) => {
        const week = event.target.closest("[data-week]");
        if (week && state.current && state.current.status !== "published") {
            state.current.week = Number(week.dataset.week);
            markDirty();
            rememberRowsLocally();
            renderEditor();
            return;
        }
        const move = event.target.closest("[data-move]");
        if (move) {
            rememberRowsLocally();
            const row = move.closest("tr");
            const rows = [...row.parentNode.children];
            const index = rows.indexOf(row);
            const next = move.dataset.move === "up" ? index - 1 : index + 1;
            if (next < 0 || next >= state.current.rows.length) {
                return;
            }
            const [item] = state.current.rows.splice(index, 1);
            state.current.rows.splice(next, 0, item);
            markDirty();
            renderEditor();
            return;
        }
        if (event.target.closest("[data-remove-row]")) {
            rememberRowsLocally();
            const row = event.target.closest("tr");
            const index = [...row.parentNode.children].indexOf(row);
            state.current.rows.splice(index, 1);
            markDirty();
            renderEditor();
            return;
        }
        if (event.target.closest("#add-row")) {
            rememberRowsLocally();
            state.current.rows.push(blankRow());
            markDirty();
            renderEditor();
            return;
        }
        if (event.target.closest("#save-sheet")) {
            await saveSheet();
            return;
        }
        if (event.target.closest("#publish-sheet")) {
            await publishSheet();
            return;
        }
        if (event.target.closest("#unpublish-sheet")) {
            try {
                state.current = await api(`/api/substitutions/${state.current.id}/unpublish`, {
                    method: "POST",
                    body: "{}",
                });
                state.dirty = false;
                await refreshList();
                render();
                showNotice("Лист снова черновик. В расписании студентов его нет.", "ok");
            } catch (error) {
                showNotice(error.message);
            }
            return;
        }
        if (event.target.closest("#notify-sheet")) {
            try {
                const result = await api(`/api/substitutions/${state.current.id}/notify`, {
                    method: "POST",
                    body: "{}",
                });
                state.current = result.sheet;
                render();
                const notify = result.notify || {};
                showNotice(notify.sent ? notify.warning || "Сообщение отправлено." : notify.error, notify.sent && !notify.warning ? "ok" : "");
            } catch (error) {
                showNotice(error.message);
            }
            return;
        }
        if (event.target.closest("#delete-sheet")) {
            if (!window.confirm("Удалить этот лист замены?")) {
                return;
            }
            try {
                await api(`/api/substitutions/${state.current.id}`, { method: "DELETE" });
                state.current = null;
                state.dirty = false;
                await refreshList();
                render();
                showNotice("Лист удалён.", "ok");
            } catch (error) {
                showNotice(error.message);
            }
        }
    });
}

async function init() {
    const me = await api("/api/auth/me");
    if (!me.authenticated || me.role !== "admin") {
        window.location.href = "/admin";
        return;
    }
    const [bootstrap, chat] = await Promise.all([
        api("/api/bootstrap"),
        api("/api/substitutions/notify-chat"),
    ]);
    state.groups = bootstrap.groups || [];
    state.subjects = bootstrap.subjects || [];
    state.teachers = bootstrap.teachers || [];
    state.chatId = chat.chat_id || "";
    $("#chat-id").value = state.chatId;
    fillLists();
    await refreshList();
    render();
    bindEditor();

    $("#sheet-list").addEventListener("click", (event) => {
        const card = event.target.closest("[data-open]");
        if (card) {
            openSheet(card.dataset.open);
        }
    });

    $("#new-sheet").addEventListener("click", async () => {
        if (state.dirty && !window.confirm("Есть несохранённые правки. Создать новый лист без сохранения?")) {
            return;
        }
        try {
            const created = await api("/api/substitutions", {
                method: "POST",
                body: JSON.stringify({ sheet_date: defaultDate(), week: 1, rows: [] }),
            });
            state.current = created;
            state.dirty = false;
            await refreshList();
            render();
            showNotice("Черновик создан. Заполните таблицу и сохраните — опубликовать можно позже.", "ok");
        } catch (error) {
            showNotice(error.message);
        }
    });

    $("#chat-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const saved = await api("/api/substitutions/notify-chat", {
                method: "PUT",
                body: JSON.stringify({ chat_id: $("#chat-id").value.trim() }),
            });
            state.chatId = saved.chat_id || "";
            showNotice(
                state.chatId
                    ? "Чат для уведомлений сохранён."
                    : "Чат очищен. Публикация пройдёт без сообщения в MAX.",
                "ok",
            );
        } catch (error) {
            showNotice(error.message);
        }
    });

    window.addEventListener("beforeunload", (event) => {
        if (!state.dirty) {
            return;
        }
        event.preventDefault();
        event.returnValue = "";
    });
}

init().catch((error) => {
    showNotice(error.message || "Не удалось открыть замены.");
});
