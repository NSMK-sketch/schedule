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
    teacherSubjects: [],
    links: [],
    slots: [],
    slotIndex: new Map(),
    subjectById: new Map(),
    teacherById: new Map(),
    groupByName: new Map(),
    subjectByName: new Map(),
    teacherByName: new Map(),
    chatId: "",
    dirty: false,
};

let suggestionSeq = 0;

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

function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function api(url, options = {}, attempt = 0) {
    const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
        ...options,
    });
    if (response.status === 429 && attempt < 2) {
        await wait(700 * (attempt + 1));
        return api(url, options, attempt + 1);
    }
    if (response.status === 401) {
        window.location.href = "/admin";
        throw new Error("Требуется авторизация.");
    }
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

function normKey(value) {
    return String(value || "").trim().toLocaleLowerCase("ru").replace(/\s+/g, " ");
}

function teacherLabels(teacher) {
    return [...new Set(
        [paperTeacher(teacher.full_name), teacher.short_name, teacher.full_name]
            .map((value) => String(value || "").trim())
            .filter(Boolean),
    )];
}

function indexCatalog() {
    state.groupByName = new Map();
    state.groups.forEach((group) => {
        state.groupByName.set(normKey(group.name), group);
    });
    state.subjectByName = new Map();
    state.subjects.forEach((subject) => {
        state.subjectByName.set(normKey(subject.name), subject);
        if (subject.short_name) {
            state.subjectByName.set(normKey(subject.short_name), subject);
        }
    });
    state.teacherByName = new Map();
    state.teacherById = new Map();
    state.teachers.forEach((teacher) => {
        state.teacherById.set(Number(teacher.id), teacher);
        teacherLabels(teacher).forEach((label) => {
            state.teacherByName.set(normKey(label), teacher);
        });
    });
    state.subjectById = new Map();
    state.subjects.forEach((subject) => {
        state.subjectById.set(Number(subject.id), subject);
    });
    state.slotIndex = new Map();
    state.slots.forEach((slot) => {
        const key = [
            Number(slot.group_id),
            Number(slot.week),
            Number(slot.weekday),
            Number(slot.period),
        ].join("|");
        if (!state.slotIndex.has(key)) {
            state.slotIndex.set(key, []);
        }
        state.slotIndex.get(key).push(slot);
    });
}

function parsePeriods(value) {
    const text = String(value || "").trim();
    if (!text || text.length > 40) {
        return null;
    }
    const periods = [];
    for (const chunk of text.replace(/\./g, ",").split(/[\s,;]+/)) {
        if (!chunk) {
            continue;
        }
        if (!/^\d+$/.test(chunk)) {
            return null;
        }
        const number = Number(chunk);
        if (number < 1 || number > 8 || periods.includes(number)) {
            if (number < 1 || number > 8) {
                return null;
            }
            continue;
        }
        periods.push(number);
    }
    return periods.length ? periods : null;
}

function teacherSheetName(teacher) {
    if (!teacher) {
        return "";
    }
    return String(teacher.full_name || "").trim() || String(teacher.short_name || "").trim();
}

function plannedLesson(groupId, week, weekday, periods) {
    const subjects = [];
    const teachers = [];
    const seenSubjects = new Set();
    const seenTeachers = new Set();
    periods.forEach((period) => {
        const slots = state.slotIndex.get(`${groupId}|${week}|${weekday}|${period}`) || [];
        slots.forEach((slot) => {
            const subject = state.subjectById.get(Number(slot.subject_id));
            const subjectName = subject ? String(subject.name || "").trim() : "";
            const subjectKey = normKey(subjectName);
            if (subjectName && !seenSubjects.has(subjectKey)) {
                seenSubjects.add(subjectKey);
                subjects.push(subjectName);
            }
            [slot.teacher_id, slot.teacher2_id].forEach((teacherId) => {
                const teacher = state.teacherById.get(Number(teacherId));
                const name = teacherSheetName(teacher);
                const key = normKey(name);
                if (name && !seenTeachers.has(key)) {
                    seenTeachers.add(key);
                    teachers.push(name);
                }
            });
        });
    });
    return {
        subject: subjects.join(", "),
        teacher: teachers.join(", "),
    };
}

function setAutoField(row, field, dataKey, next) {
    const input = row.querySelector(`[data-field="${field}"]`);
    if (!input || input.disabled) {
        return false;
    }
    const previous = row.dataset[dataKey] || "";
    const current = input.value.trim();
    if (current && current !== previous) {
        return false;
    }
    row.dataset[dataKey] = next;
    if (current === next) {
        return false;
    }
    input.value = next;
    return true;
}

function applyPlannedLesson(row) {
    if (!state.current || state.current.status === "published") {
        return false;
    }
    const periodsText = fieldValue(row, "periods").trim();
    const periods = parsePeriods(periodsText);
    if (periodsText && !periods) {
        return false;
    }
    const group = findGroup(fieldValue(row, "group_name"));
    const dateInput = $("#sheet-date");
    const date = dateInput ? dateInput.value : state.current.sheet_date;
    const weekday = date ? weekdayOf(date) : 0;
    const week = Number(state.current.week);
    let planned = { subject: "", teacher: "" };
    if (group && periods && weekday >= 1 && weekday <= 6 && (week === 1 || week === 2)) {
        planned = plannedLesson(group.id, week, weekday, periods);
    }
    const subjectChanged = setAutoField(row, "old_subject", "autoSubject", planned.subject);
    const teacherChanged = setAutoField(row, "absent_teacher", "autoTeacher", planned.teacher);
    return subjectChanged || teacherChanged;
}

function findGroup(name) {
    return state.groupByName.get(normKey(name)) || null;
}

function findSubject(name) {
    return state.subjectByName.get(normKey(name)) || null;
}

function findTeacher(name) {
    return state.teacherByName.get(normKey(name)) || null;
}

function subjectsFor(group, teacher) {
    if (!group && !teacher) {
        return state.subjects;
    }
    const ids = new Set();
    if (group && teacher) {
        state.links.forEach((link) => {
            if (link.groupId === group.id && link.teacherId === teacher.id && link.subjectId) {
                ids.add(link.subjectId);
            }
        });
        return state.subjects.filter((subject) => ids.has(subject.id));
    }
    if (group) {
        state.links.forEach((link) => {
            if (link.groupId === group.id && link.subjectId) {
                ids.add(link.subjectId);
            }
        });
        return state.subjects.filter((subject) => ids.has(subject.id));
    }
    state.teacherSubjects.forEach((link) => {
        if (Number(link.teacher_id) === teacher.id) {
            ids.add(Number(link.subject_id));
        }
    });
    state.links.forEach((link) => {
        if (link.teacherId === teacher.id && link.subjectId) {
            ids.add(link.subjectId);
        }
    });
    return state.subjects.filter((subject) => ids.has(subject.id));
}

function teachersFor(group, subject) {
    if (!group && !subject) {
        return state.teachers;
    }
    const ids = new Set();
    if (group && subject) {
        state.links.forEach((link) => {
            if (link.groupId === group.id && link.subjectId === subject.id) {
                ids.add(link.teacherId);
            }
        });
        return state.teachers.filter((teacher) => ids.has(teacher.id));
    }
    if (group) {
        state.links.forEach((link) => {
            if (link.groupId === group.id) {
                ids.add(link.teacherId);
            }
        });
        return state.teachers.filter((teacher) => ids.has(teacher.id));
    }
    state.teacherSubjects.forEach((link) => {
        if (Number(link.subject_id) === subject.id) {
            ids.add(Number(link.teacher_id));
        }
    });
    state.links.forEach((link) => {
        if (link.subjectId === subject.id) {
            ids.add(link.teacherId);
        }
    });
    return state.teachers.filter((teacher) => ids.has(teacher.id));
}

function fillGroupList() {
    const node = $("#group-options");
    if (!node) {
        return;
    }
    const names = state.groups
        .slice()
        .sort((a, b) => {
            const course = (Number(a.course) || 0) - (Number(b.course) || 0);
            if (course) {
                return course;
            }
            return String(a.name).localeCompare(String(b.name), "ru");
        })
        .map((group) => group.name);
    node.innerHTML = names.map((name) => `<option value="${esc(name)}"></option>`).join("");
}

function setOptions(listId, values) {
    const node = document.getElementById(listId);
    if (!node) {
        return;
    }
    const unique = [];
    const seen = new Set();
    values.forEach((value) => {
        const text = String(value || "").trim();
        const key = normKey(text);
        if (!text || seen.has(key)) {
            return;
        }
        seen.add(key);
        unique.push(text);
    });
    unique.sort((a, b) => a.localeCompare(b, "ru"));
    node.innerHTML = unique.map((value) => `<option value="${esc(value)}"></option>`).join("");
}

function fieldValue(row, name) {
    const node = row.querySelector(`[data-field="${name}"]`);
    return node ? node.value : "";
}

function refreshRowSuggestions(row, skipField) {
    const group = findGroup(fieldValue(row, "group_name"));
    [
        ["new_subject", "new_teacher"],
        ["old_subject", "absent_teacher"],
    ].forEach(([subjectField, teacherField]) => {
        const subject = findSubject(fieldValue(row, subjectField));
        const teacher = findTeacher(fieldValue(row, teacherField));
        if (skipField !== subjectField) {
            const listId = row.querySelector(`[data-field="${subjectField}"]`)?.getAttribute("list");
            setOptions(listId, subjectsFor(group, teacher).map((item) => item.name));
        }
        if (skipField !== teacherField) {
            const listId = row.querySelector(`[data-field="${teacherField}"]`)?.getAttribute("list");
            const labels = [];
            teachersFor(group, subject).forEach((item) => {
                const name = String(item.full_name || "").trim();
                if (name) {
                    labels.push(name);
                }
            });
            setOptions(listId, labels);
        }
    });
}

function groupLabel(row) {
    if (row.group_name) {
        return row.group_name;
    }
    const group = state.groups.find((item) => String(item.id) === String(row.group_id || ""));
    return group ? group.name : "";
}

function suggestionList() {
    suggestionSeq += 1;
    return `suggest-${suggestionSeq}`;
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
    const newSubjectList = suggestionList();
    const newTeacherList = suggestionList();
    const oldSubjectList = suggestionList();
    const absentTeacherList = suggestionList();
    return `
        <tr data-auto-subject="${esc(row.auto_subject || "")}" data-auto-teacher="${esc(row.auto_teacher || "")}">
            <td>
                <input data-field="group_name" list="group-options" autocomplete="off" value="${esc(groupLabel(row))}"${disabled}>
            </td>
            <td class="period">
                <input data-field="periods" value="${esc(row.periods_label || "")}" placeholder="3,4"${disabled}>
            </td>
            <td>
                <input data-field="new_subject" list="${newSubjectList}" autocomplete="off" value="${esc(row.new_subject || "")}"${disabled}>
                <datalist id="${newSubjectList}"></datalist>
            </td>
            <td class="room">
                <input data-field="new_room" value="${esc(row.new_room || "")}" placeholder="407"${disabled}>
            </td>
            <td>
                <input data-field="new_teacher" list="${newTeacherList}" autocomplete="off" value="${esc(row.new_teacher || "")}"${disabled}>
                <datalist id="${newTeacherList}"></datalist>
            </td>
            <td>
                <input data-field="old_subject" list="${oldSubjectList}" autocomplete="off" value="${esc(row.old_subject || "")}"${disabled}>
                <datalist id="${oldSubjectList}"></datalist>
            </td>
            <td>
                <input data-field="absent_teacher" list="${absentTeacherList}" autocomplete="off" value="${esc(row.absent_teacher || "")}"${disabled}>
                <datalist id="${absentTeacherList}"></datalist>
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
                <button type="button" id="print-sheet">Печать</button>
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
    let filledFromSchedule = false;
    root.querySelectorAll("#change-rows tr").forEach((row) => {
        if (applyPlannedLesson(row)) {
            filledFromSchedule = true;
        }
        refreshRowSuggestions(row);
    });
    if (filledFromSchedule) {
        markDirty();
    }
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
        const groupName = row.querySelector("[data-field='group_name']").value.trim();
        const group = findGroup(groupName);
        return {
            group_id: group ? group.id : "",
            group_name: groupName,
            periods: row.querySelector("[data-field='periods']").value,
            new_subject: row.querySelector("[data-field='new_subject']").value,
            new_room: row.querySelector("[data-field='new_room']").value,
            new_teacher: row.querySelector("[data-field='new_teacher']").value,
            old_subject: row.querySelector("[data-field='old_subject']").value,
            absent_teacher: row.querySelector("[data-field='absent_teacher']").value,
            auto_subject: row.dataset.autoSubject || "",
            auto_teacher: row.dataset.autoTeacher || "",
        };
    });
    return {
        sheet_date: $("#sheet-date").value,
        week: Number(sheet.week),
        rows,
    };
}

function lessonLabel(row) {
    const subject = String(row.new_subject || "").trim();
    const room = String(row.new_room || "").trim();
    const teacher = String(row.new_teacher || "").trim();
    if (!subject && !room && !teacher) {
        return "снято";
    }
    if (room && subject) {
        return `${subject} (ауд.${room})`;
    }
    if (room) {
        return `ауд.${room}`;
    }
    return subject;
}

function filledPrintRows(rows) {
    return rows.filter((row) =>
        [
            row.group_name,
            row.periods,
            row.new_subject,
            row.new_room,
            row.new_teacher,
            row.old_subject,
            row.absent_teacher,
        ].some((value) => String(value || "").trim()),
    );
}

function renderPrintRoot(payload) {
    const root = $("#print-root");
    if (!root) {
        return;
    }
    const dateLabel = payload.sheet_date
        ? payload.sheet_date.split("-").reverse().join(".")
        : "";
    const rows = filledPrintRows(payload.rows);
    const body = rows.length
        ? rows
              .map(
                  (row) => `
            <tr>
                <td>${esc(row.group_name)}</td>
                <td class="center">${esc(String(row.periods || "").trim())}</td>
                <td>${esc(lessonLabel(row))}</td>
                <td>${esc(String(row.new_teacher || "").trim())}</td>
                <td>${esc(String(row.old_subject || "").trim())}</td>
                <td>${esc(String(row.absent_teacher || "").trim())}</td>
            </tr>`,
              )
              .join("")
        : `<tr><td colspan="6" class="center">Строк нет.</td></tr>`;
    root.innerHTML = `
        <table class="paper">
            <thead>
                <tr><th class="paper-title" colspan="6">${esc(previewTitle(payload.sheet_date, payload.week))}</th></tr>
                <tr>
                    <th class="col-group">Группа</th>
                    <th class="col-period">пара</th>
                    <th colspan="2">${esc(dateLabel)}</th>
                    <th colspan="2">Заменяемый предмет;<br>Отсутствующий преподаватель</th>
                </tr>
            </thead>
            <tbody>${body}</tbody>
        </table>
        <p class="paper-note">Замена только на ${esc(dateLabel)}. На следующей неделе в этот день снова обычное расписание.</p>
    `;
}

function printCurrentSheet() {
    const payload = readSheetFromDom();
    if (!filledPrintRows(payload.rows).length) {
        showNotice("Добавьте строки — печатать нечего.");
        return;
    }
    renderPrintRoot(payload);
    window.print();
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
        const field = event.target.closest("#change-rows [data-field]");
        if (!field) {
            return;
        }
        const row = field.closest("tr");
        if (field.dataset.field === "group_name" || field.dataset.field === "periods") {
            applyPlannedLesson(row);
        }
        refreshRowSuggestions(row, field.dataset.field);
    });
    $("#editor").addEventListener("focusin", (event) => {
        const field = event.target.closest("#change-rows [data-field]");
        if (!field || field.dataset.field === "periods" || field.dataset.field === "new_room") {
            return;
        }
        refreshRowSuggestions(field.closest("tr"));
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
            document.querySelectorAll("#change-rows tr").forEach((row) => {
                applyPlannedLesson(row);
                refreshRowSuggestions(row);
            });
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
        if (event.target.closest("#print-sheet")) {
            printCurrentSheet();
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
    state.chatId = $("#chat-id").value.trim();
    const bootstrap = await api("/api/bootstrap");
    state.groups = bootstrap.groups || [];
    state.subjects = bootstrap.subjects || [];
    state.teachers = bootstrap.teachers || [];
    state.teacherSubjects = bootstrap.teacher_subjects || [];
    state.links = (bootstrap.schedule_links || []).map((link) => ({
        groupId: Number(link.group_id),
        teacherId: Number(link.teacher_id),
        subjectId: Number(link.subject_id),
    }));
    state.slots = bootstrap.schedule_slots || [];
    indexCatalog();
    fillGroupList();
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

    window.addEventListener("beforeprint", () => {
        if (!state.current || !$("#sheet-date")) {
            return;
        }
        renderPrintRoot(readSheetFromDom());
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
