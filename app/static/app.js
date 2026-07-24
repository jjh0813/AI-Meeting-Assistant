let token = sessionStorage.getItem("noting_token");
let me = null;
let transcripts = [];
let dashboardTasks = [];
let archivedTranscripts = [];
let archivedTasks = [];
let calendarCursor = new Date();
let selectedCalendarDate = new Date();
let currentTranscriptId = null;
let currentPage = "workspace";
let detailReturnPage = "workspace";
let analysisPollId = null;
let recorder = {
  stream: null,
  context: null,
  source: null,
  processor: null,
  gain: null,
  chunks: [],
  startedAt: null,
  timer: null,
};

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? "").replace(
  /[&<>'"]/g,
  char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char],
);

function showToast(message, type = "") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`.trim();
  toast.textContent = message;
  $("toast-region").appendChild(toast);
  setTimeout(() => toast.remove(), 4200);
}

function setMessage(id, message, type = "") {
  const element = $(id);
  element.textContent = message;
  element.className = `form-message ${type}`.trim();
}

function showAuth(tab) {
  const loginMode = tab === "login";
  $("login-pane").classList.toggle("hidden", !loginMode);
  $("signup-pane").classList.toggle("hidden", loginMode);
  $("tab-login").classList.toggle("active", loginMode);
  $("tab-signup").classList.toggle("active", !loginMode);
  $("auth-title").textContent = loginMode ? "다시 만나서 반가워요." : "팀 작업대를 요청하세요.";
  $("auth-subtitle").textContent = loginMode
    ? "내 부서의 회의 작업대로 로그인하세요."
    : "관리자 승인 후 같은 부서의 회의 요약을 볼 수 있습니다.";
}

function toggleSidebar(open) {
  $("sidebar").classList.toggle("open", open);
  $("mobile-overlay").classList.toggle("hidden", !open);
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = response.statusText || "요청을 처리하지 못했습니다.";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {
      // Non-JSON responses still use the HTTP status text.
    }
    if (response.status === 401 && token) logout();
    throw new Error(detail);
  }
  return response;
}

async function login(event) {
  event?.preventDefault();
  const button = $("login-submit");
  setMessage("login-message", "");
  button.disabled = true;
  button.firstChild.textContent = "로그인 중 ";
  const body = new URLSearchParams({
    username: $("login-username").value.trim(),
    password: $("login-password").value,
  });
  try {
    const response = await fetch("/auth/login", { method: "POST", body });
    if (!response.ok) throw new Error("아이디 또는 비밀번호를 확인해 주세요.");
    token = (await response.json()).access_token;
    sessionStorage.setItem("noting_token", token);
    await loadMe();
  } catch (error) {
    setMessage("login-message", error.message);
  } finally {
    button.disabled = false;
    button.firstChild.textContent = "Noting 시작하기 ";
  }
}

async function signup(event) {
  event?.preventDefault();
  const payload = {
    username: $("signup-username").value.trim(),
    password: $("signup-password").value,
    department: $("signup-department").value,
    role: $("signup-role").value,
  };
  try {
    await api("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setMessage("signup-message", "가입 요청을 보냈습니다. 관리자 승인 후 로그인해 주세요.", "success");
  } catch (error) {
    setMessage("signup-message", error.message);
  }
}

async function loadMe() {
  me = await (await api("/me")).json();
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("profile-name").textContent = me.username;
  $("profile-meta").textContent = `${me.department} · ${me.role}`;
  $("greeting-name").textContent = me.username;
  $("workspace-caption").textContent = `${me.department} 부서 · AI 회의 요약`;
  $("avatar").textContent = me.username.slice(0, 1).toUpperCase();
  const approved = me.status === "승인";
  $("pending-view").classList.toggle("hidden", approved);
  $("approved-view").classList.toggle("hidden", !approved);
  $("approval-badge").textContent = approved ? "승인됨" : "승인 대기";
  $("approval-badge").classList.toggle("processing", !approved);
  const admin = approved && me.role === "관리자";
  $("admin-nav").classList.toggle("hidden", !admin);
  $("pii-button").classList.toggle("hidden", !admin);
  if (approved) await refreshDashboard();
}

function logout() {
  sessionStorage.removeItem("noting_token");
  token = null;
  me = null;
  transcripts = [];
  dashboardTasks = [];
  archivedTranscripts = [];
  archivedTasks = [];
  if (analysisPollId) clearTimeout(analysisPollId);
  $("app-view").classList.add("hidden");
  $("auth-view").classList.remove("hidden");
  closeComposer();
  closeAdmin();
  hideResult();
}

function dateKey(date) {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function formatDate(value, withTime = false) {
  if (!value) return "등록일 미확인";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "등록일 미확인";
  return withTime
    ? date.toLocaleString("ko-KR", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("ko-KR", { month: "short", day: "numeric", weekday: "short" });
}

function parseDue(value) {
  if (!value) return null;
  const text = String(value).trim();
  let match = text.match(/(20\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})/);
  if (match) return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  match = text.match(/(\d{1,2})월\s*(\d{1,2})일?/);
  if (match) return new Date(new Date().getFullYear(), Number(match[1]) - 1, Number(match[2]));
  return null;
}

function isActiveTask(task) {
  return task.status !== "완료" && task.status !== "변경됨";
}

function analysisLabel(status) {
  return {
    completed: "분석 완료",
    processing: "분석 중",
    failed: "분석 실패",
    pending: "분석 대기",
  }[status] || "분석 대기";
}

async function refreshDashboard() {
  try {
    transcripts = await (await api("/transcripts")).json();
    transcripts.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0) || b.id - a.id);
    const taskResults = await Promise.all(transcripts.map(async transcript => {
      try {
        const data = await (await api(`/transcripts/${transcript.id}/tasks`)).json();
        return { transcript, data };
      } catch (_) {
        return { transcript, data: { tasks: [] } };
      }
    }));
    dashboardTasks = taskResults.flatMap(({ transcript, data }) =>
      (data.tasks || []).map(task => ({ ...task, transcriptId: transcript.id, transcriptTitle: transcript.title })),
    );
    renderDashboardStats();
    renderSidebarMeetings();
    renderCalendar();
    renderEvents();
    renderDateMeetings();
    renderAllMeetings();
    populateTaskOwners();
    renderTasksPage();
  } catch (error) {
    showToast(`목록을 불러오지 못했습니다: ${error.message}`, "error");
  }
}

function renderDashboardStats() {
  const activeTasks = dashboardTasks.filter(isActiveTask);
  $("meeting-total").textContent = transcripts.length;
  $("analysis-total").textContent = transcripts.filter(item => item.analysis_status === "completed" || item.summary).length;
  $("active-task-total").textContent = activeTasks.length;
  $("task-count").textContent = activeTasks.length;
}

function renderSidebarMeetings() {
  const box = $("sidebar-meetings");
  if (!transcripts.length) {
    box.innerHTML = '<div class="empty-state">아직 저장된 회의가 없습니다.</div>';
    return;
  }
  box.innerHTML = transcripts.slice(0, 7).map(item => `
    <button class="sidebar-meeting" type="button" onclick="openTranscript(${item.id})">
      <i></i><span><b>${escapeHtml(item.title || `회의록 #${item.id}`)}</b><small>${escapeHtml(formatDate(item.created_at))} · ${escapeHtml(analysisLabel(item.analysis_status))}</small></span>
    </button>
  `).join("");
}

function changeMonth(direction) {
  calendarCursor = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth() + direction, 1);
  selectedCalendarDate = new Date(calendarCursor);
  renderCalendar();
  renderDateMeetings();
}

function selectCalendarDate(year, month, day) {
  selectedCalendarDate = new Date(year, month, day);
  calendarCursor = new Date(year, month, 1);
  renderCalendar();
  renderDateMeetings();
  if (window.innerWidth < 801) $("date-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderCalendar() {
  $("calendar-month").textContent = `${calendarCursor.getFullYear()}년 ${calendarCursor.getMonth() + 1}월`;
  const first = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth(), 1);
  const start = new Date(first);
  start.setDate(1 - first.getDay());
  const meetingDates = new Set(
    transcripts.map(item => new Date(item.created_at)).filter(date => !Number.isNaN(date.getTime())).map(dateKey),
  );
  const taskDates = new Set(
    dashboardTasks.filter(isActiveTask).map(task => parseDue(task.due)).filter(Boolean).map(dateKey),
  );
  const today = new Date();
  let html = "";
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    const key = dateKey(day);
    const classes = [
      day.getMonth() !== calendarCursor.getMonth() ? "outside" : "",
      key === dateKey(today) ? "today" : "",
      key === dateKey(selectedCalendarDate) ? "selected" : "",
      meetingDates.has(key) ? "has-meeting" : "",
      taskDates.has(key) ? "has-task" : "",
    ].filter(Boolean).join(" ");
    html += `<button type="button" class="${classes}" onclick="selectCalendarDate(${day.getFullYear()},${day.getMonth()},${day.getDate()})" aria-label="${day.toLocaleDateString("ko-KR")}">${day.getDate()}</button>`;
  }
  $("calendar-days").innerHTML = html;
}

function renderEvents() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const active = dashboardTasks.filter(isActiveTask);
  const dated = active
    .map(task => ({ ...task, parsedDue: parseDue(task.due) }))
    .filter(task => !task.parsedDue || task.parsedDue >= today);
  dated.sort((a, b) => {
    if (a.parsedDue && b.parsedDue) return a.parsedDue - b.parsedDue;
    if (a.parsedDue) return -1;
    if (b.parsedDue) return 1;
    return b.id - a.id;
  });
  const items = dated.slice(0, 6);
  $("task-progress").textContent = `${items.length}개`;
  if (!items.length) {
    $("event-list").innerHTML = '<div class="empty-state">다가오는 이벤트가 없습니다.<br />회의에서 추출된 업무 시작과 마감 일정이 이곳에 표시됩니다.</div>';
    return;
  }
  $("event-list").innerHTML = items.map(task => {
    const eventType = task.parsedDue ? "마감 일정" : "시작 업무";
    const icon = task.parsedDue ? "◷" : "→";
    return `
    <div class="event-item">
      <span class="event-type-icon ${task.parsedDue ? "deadline" : "start"}" aria-hidden="true">${icon}</span>
      <div class="event-copy"><button type="button" onclick="openTranscript(${task.transcriptId})">${escapeHtml(task.task || "업무 항목")}</button><small>${escapeHtml(task.assignee || "담당 미지정")} · ${escapeHtml(task.transcriptTitle || `회의록 #${task.transcriptId}`)}</small></div>
      <span class="event-due">${escapeHtml(task.parsedDue ? `마감 · ${task.due}` : eventType)}</span>
    </div>
  `;
  }).join("");
}

function renderDateMeetings() {
  $("selected-date-title").textContent = `${selectedCalendarDate.getMonth() + 1}월 ${selectedCalendarDate.getDate()}일의 회의`;
  const selected = transcripts.filter(item => {
    const created = new Date(item.created_at);
    return !Number.isNaN(created.getTime()) && dateKey(created) === dateKey(selectedCalendarDate);
  });
  if (!selected.length) {
    $("meeting-list").innerHTML = '<div class="empty-state">이 날짜에 등록된 회의가 없습니다.<br />다른 날짜를 선택하거나 새 회의를 가져오세요.</div>';
    return;
  }
  $("meeting-list").innerHTML = selected.map(item => {
    const status = item.analysis_status || (item.summary ? "completed" : "pending");
    return `
      <button class="meeting-row" type="button" onclick="openTranscript(${item.id})">
        <span class="meeting-row-date">${escapeHtml(formatDate(item.created_at))}<br />${escapeHtml(item.department)}</span>
        <span><b class="meeting-row-title">${escapeHtml(item.title || `회의록 #${item.id}`)}</b><small class="meeting-row-summary">${escapeHtml(item.summary || item.masked_content || "회의 내용을 확인하세요.")}</small></span>
        <span class="analysis-tag ${status}">${escapeHtml(analysisLabel(status))}</span>
      </button>
    `;
  }).join("");
}

function showPage(page, targetId = null) {
  currentPage = page;
  currentTranscriptId = null;
  $("meeting-detail").classList.add("hidden");
  const views = {
    workspace: "dashboard-view",
    meetings: "all-meetings-view",
    tasks: "tasks-view",
    archive: "archive-view",
  };
  Object.values(views).forEach(id => $(id).classList.add("hidden"));
  $(views[page] || views.workspace).classList.remove("hidden");
  ["workspace", "meetings", "tasks", "archive"].forEach(name => {
    $(`nav-${name}`).classList.toggle("active", name === page);
  });
  const headers = {
    workspace: ["WORKSPACE", `${me?.department || ""} 부서 · AI 회의 요약`],
    meetings: ["ALL MEETINGS", "내 부서의 전체 회의"],
    tasks: ["TASKS", "회의에서 추출된 할 일"],
    archive: ["ARCHIVE", "보관된 회의 관리"],
  };
  const [label, caption] = headers[page] || headers.workspace;
  $("page-header-label").textContent = label;
  $("workspace-caption").textContent = caption;
  $("detail-menu").classList.add("hidden");
  hideTitleEditor();
  toggleSidebar(false);
  if (page === "archive") loadArchive();
  if (page === "meetings") renderAllMeetings();
  if (page === "tasks") renderTasksPage();
  if (targetId) setTimeout(() => $(targetId)?.scrollIntoView({ behavior: "smooth", block: "start" }), 40);
  else window.scrollTo({ top: 0, behavior: "smooth" });
}

function showDashboard(targetId = null) {
  showPage("workspace", targetId);
}

function returnFromDetail() {
  showPage(detailReturnPage || "workspace");
}

function focusAssistant() {
  showPage("workspace", "qa-dashboard");
  setTimeout(() => $("qa-dashboard-input").focus(), 450);
}

function renderAllMeetings() {
  const box = $("all-meetings-list");
  if (!box) return;
  const query = $("meeting-search").value.trim().toLowerCase();
  const status = $("meeting-status-filter").value;
  const sort = $("meeting-sort").value;
  const filtered = transcripts.filter(item => {
    const itemStatus = item.analysis_status || (item.summary ? "completed" : "pending");
    const text = `${item.title || ""} ${item.summary || ""} ${item.masked_content || ""}`.toLowerCase();
    return (!query || text.includes(query)) && (status === "all" || itemStatus === status);
  });
  filtered.sort((a, b) => {
    if (sort === "oldest") return new Date(a.created_at || 0) - new Date(b.created_at || 0);
    if (sort === "title") return String(a.title || "").localeCompare(String(b.title || ""), "ko");
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });
  $("all-meeting-count").textContent = filtered.length;
  if (!filtered.length) {
    box.innerHTML = '<div class="empty-state paper-panel">조건에 맞는 회의가 없습니다.</div>';
    return;
  }
  box.innerHTML = filtered.map(item => {
    const itemStatus = item.analysis_status || (item.summary ? "completed" : "pending");
    return `
      <article class="meeting-card paper-panel">
        <div class="meeting-card-top"><span class="meeting-group"><i></i>${escapeHtml(item.department)}</span><span class="analysis-tag ${itemStatus}">${escapeHtml(analysisLabel(itemStatus))}</span></div>
        <button class="meeting-card-open" type="button" onclick="openTranscript(${item.id})"><h2>${escapeHtml(item.title || `회의록 #${item.id}`)}</h2><p>${escapeHtml(item.summary || item.masked_content || "회의 내용을 확인하세요.")}</p></button>
        <div class="meeting-card-foot"><span>${escapeHtml(formatDate(item.created_at, true))}</span><div><button type="button" onclick="archiveTranscript(${item.id})">보관</button><button type="button" onclick="openTranscript(${item.id})">회의 열기 →</button></div></div>
      </article>
    `;
  }).join("");
}

function populateTaskOwners() {
  const select = $("task-owner-filter");
  if (!select) return;
  const selected = select.value;
  const owners = [...new Set(dashboardTasks.map(task => task.assignee).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ko"));
  select.innerHTML = '<option value="all">모든 담당자</option>' + owners.map(owner => `<option value="${escapeHtml(owner)}">${escapeHtml(owner)}</option>`).join("");
  select.value = owners.includes(selected) ? selected : "all";
}

function taskPriority(task) {
  const due = parseDue(task.due);
  if (!due) return { key: "low", label: "낮음" };
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.ceil((due - today) / 86400000);
  if (days <= 3) return { key: "high", label: days < 0 ? "지연" : "긴급" };
  if (days <= 7) return { key: "medium", label: "중요" };
  return { key: "low", label: "낮음" };
}

function renderTasksPage() {
  const box = $("tasks-page-list");
  if (!box) return;
  const query = $("task-search").value.trim().toLowerCase();
  const owner = $("task-owner-filter").value;
  const status = $("task-status-filter").value;
  const filtered = dashboardTasks.filter(task => {
    const text = `${task.task || ""} ${task.request || ""} ${task.assignee || ""}`.toLowerCase();
    return (!query || text.includes(query))
      && (owner === "all" || task.assignee === owner)
      && (status === "all" || task.status === status);
  });
  const total = dashboardTasks.filter(task => task.status !== "변경됨").length;
  const completed = dashboardTasks.filter(task => task.status === "완료").length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  $("task-progress-percent").textContent = `${percent}%`;
  $("task-progress-copy").textContent = `${completed} / ${total} 완료`;
  $("task-progress-ring").style.setProperty("--progress", `${percent * 3.6}deg`);
  if (!filtered.length) {
    box.innerHTML = '<div class="empty-state">조건에 맞는 할 일이 없습니다.</div>';
    return;
  }
  box.innerHTML = filtered.map(task => {
    const priority = taskPriority(task);
    const done = task.status === "완료";
    return `
      <article class="task-page-row ${done ? "done" : ""}">
        <button class="task-checkbox ${done ? "checked" : ""}" type="button" aria-label="${escapeHtml(task.task)} 완료 상태 변경" onclick="updateTaskStatus(${task.transcriptId},${task.id},'${done ? "대기" : "완료"}',false)">✓</button>
        <div class="task-page-copy"><div><span class="priority-badge ${priority.key}">${priority.label}</span><b>${escapeHtml(task.task || "업무 항목")}</b></div><p>${escapeHtml(task.request || task.transcriptTitle || "")}</p><small>${escapeHtml(task.assignee || "담당 미지정")} · ${escapeHtml(task.due || "기한 미정")} · ${escapeHtml(task.transcriptTitle || `회의록 #${task.transcriptId}`)}</small></div>
        <div class="task-row-actions"><button class="button ghost compact" type="button" onclick="openTranscript(${task.transcriptId})">회의 보기</button><button class="archive-task-button" type="button" onclick="archiveTask(${task.transcriptId},${task.id})">보관</button></div>
      </article>
    `;
  }).join("");
}

async function loadArchive() {
  const box = $("archive-list");
  box.innerHTML = '<div class="empty-state paper-panel">아카이브를 불러오고 있습니다.</div>';
  try {
    const [meetingResponse, taskResponse] = await Promise.all([
      api("/transcripts/archive"),
      api("/transcripts/tasks/archive"),
    ]);
    archivedTranscripts = await meetingResponse.json();
    archivedTasks = await taskResponse.json();
    renderArchive();
  } catch (error) {
    box.innerHTML = `<div class="analysis-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderArchive() {
  const box = $("archive-list");
  if (!box) return;
  const query = $("archive-search").value.trim().toLowerCase();
  const type = $("archive-type-filter").value;
  const meetings = archivedTranscripts
    .filter(item => type === "all" || type === "meeting")
    .filter(item => `${item.title || ""} ${item.summary || ""}`.toLowerCase().includes(query))
    .map(item => ({ ...item, archiveType: "meeting" }));
  const tasks = archivedTasks
    .filter(item => type === "all" || type === "task")
    .filter(item => `${item.task || ""} ${item.request || ""} ${item.transcript_title || ""}`.toLowerCase().includes(query))
    .map(item => ({ ...item, archiveType: "task" }));
  const filtered = [...meetings, ...tasks].sort((a, b) => new Date(b.archived_at || 0) - new Date(a.archived_at || 0));
  $("archive-count").textContent = filtered.length;
  if (!filtered.length) {
    box.innerHTML = '<div class="empty-state paper-panel">보관된 항목이 없습니다.</div>';
    return;
  }
  box.innerHTML = filtered.map(item => item.archiveType === "meeting" ? `
    <article class="archive-card paper-panel">
      <span class="archive-icon">▱</span>
      <div><span class="label-caps">MEETING</span><h2>${escapeHtml(item.title || `회의록 #${item.id}`)}</h2><p>${escapeHtml(item.summary || "저장된 요약이 없습니다.")}</p><small>보관일 ${escapeHtml(formatDate(item.archived_at, true))} · 할 일 ${item.task_count || 0}개</small></div>
      <div class="archive-actions"><button class="button ghost compact" type="button" onclick="restoreTranscript(${item.id})">복구</button><button class="delete-button" type="button" onclick="deleteArchivedTranscript(${item.id})">영구 삭제</button></div>
    </article>
  ` : `
    <article class="archive-card paper-panel">
      <span class="archive-icon task">✓</span>
      <div><span class="label-caps">TASK</span><h2>${escapeHtml(item.task || `할 일 #${item.id}`)}</h2><p>${escapeHtml(item.request || item.transcript_title || "업무 설명이 없습니다.")}</p><small>보관일 ${escapeHtml(formatDate(item.archived_at, true))} · ${escapeHtml(item.assignee || "담당 미지정")} · ${escapeHtml(item.due || "기한 미정")}</small></div>
      <div class="archive-actions"><button class="button ghost compact" type="button" onclick="restoreArchivedTask(${item.transcript_id},${item.id})">복구</button><button class="delete-button" type="button" onclick="deleteArchivedTask(${item.transcript_id},${item.id})">영구 삭제</button></div>
    </article>
  `).join("");
}

async function archiveTranscript(id) {
  try {
    await api(`/transcripts/${id}/archive`, { method: "POST" });
    await refreshDashboard();
    showToast("회의를 아카이브로 이동했습니다.");
    if (currentPage === "meetings") renderAllMeetings();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function archiveCurrentTranscript() {
  if (!currentTranscriptId) return;
  $("detail-menu").classList.add("hidden");
  const id = currentTranscriptId;
  await archiveTranscript(id);
  showPage("archive");
}

async function archiveTask(transcriptId, taskId) {
  try {
    await api(`/transcripts/${transcriptId}/tasks/${taskId}/archive`, { method: "POST" });
    await refreshDashboard();
    showToast("할 일을 아카이브로 이동했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function restoreTranscript(id) {
  try {
    await api(`/transcripts/${id}/restore`, { method: "POST" });
    await Promise.all([refreshDashboard(), loadArchive()]);
    showToast("회의를 아카이브에서 복구했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function restoreArchivedTask(transcriptId, taskId) {
  try {
    await api(`/transcripts/${transcriptId}/tasks/${taskId}/restore`, { method: "POST" });
    await Promise.all([refreshDashboard(), loadArchive()]);
    showToast("할 일을 아카이브에서 복구했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteArchivedTranscript(id) {
  const target = archivedTranscripts.find(item => item.id === id);
  if (!window.confirm(`"${target?.title || `회의록 #${id}`}"을(를) 영구 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return;
  try {
    await api(`/transcripts/${id}`, { method: "DELETE" });
    await loadArchive();
    showToast("보관된 회의를 영구 삭제했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteArchivedTask(transcriptId, taskId) {
  const target = archivedTasks.find(item => item.id === taskId);
  if (!window.confirm(`"${target?.task || `할 일 #${taskId}`}"을(를) 영구 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return;
  try {
    await api(`/transcripts/${transcriptId}/tasks/${taskId}`, { method: "DELETE" });
    await loadArchive();
    showToast("보관된 할 일을 영구 삭제했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openComposer() {
  toggleSidebar(false);
  $("composer-modal").classList.remove("hidden");
  setTimeout(() => $("new-content").focus(), 40);
}

function closeComposer() {
  $("composer-modal").classList.add("hidden");
}

function setComposerMode(mode) {
  const textMode = mode === "text";
  $("text-composer").classList.toggle("hidden", !textMode);
  $("audio-composer").classList.toggle("hidden", textMode);
  $("text-mode").classList.toggle("active", textMode);
  $("audio-mode").classList.toggle("active", !textMode);
}

async function saveText() {
  const content = $("new-content").value.trim();
  if (!content) {
    setMessage("new-message", "회의 내용을 입력해 주세요.");
    return;
  }
  const button = $("text-save-button");
  button.disabled = true;
  button.textContent = "안전하게 저장하는 중...";
  try {
    const data = await (await api("/transcripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    })).json();
    $("new-content").value = "";
    closeComposer();
    await refreshDashboard();
    await openTranscript(data.id);
    await startAutoAnalysis(data.id);
  } catch (error) {
    setMessage("new-message", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "저장하고 자동 분석 시작";
  }
}

function chooseAudioFile() {
  $("audio-file").click();
}

async function uploadSelectedAudio() {
  const file = $("audio-file").files[0];
  if (!file) return;
  await uploadAudio(file);
  $("audio-file").value = "";
}

async function uploadAudio(file) {
  setComposerMode("audio");
  setMessage("new-message", "음성을 텍스트로 변환하고 있습니다. 파일 길이에 따라 시간이 걸릴 수 있습니다.", "success");
  const body = new FormData();
  body.append("file", file, file.name);
  try {
    const transcript = await (await api("/transcripts/upload", { method: "POST", body })).json();
    closeComposer();
    await refreshDashboard();
    await openTranscript(transcript.id);
    await startAutoAnalysis(transcript.id);
  } catch (error) {
    setMessage("new-message", error.message);
  }
}

async function toggleRecording() {
  if (recorder.stream) await stopRecording();
  else await startRecording();
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setMessage("new-message", "IP 주소의 HTTP 접속에서는 브라우저가 마이크를 차단합니다. HTTPS로 접속하거나 음성 파일 업로드를 이용해 주세요.");
    return;
  }
  try {
    recorder.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recorder.context = new AudioContext();
    recorder.source = recorder.context.createMediaStreamSource(recorder.stream);
    recorder.processor = recorder.context.createScriptProcessor(4096, 1, 1);
    recorder.gain = recorder.context.createGain();
    recorder.gain.gain.value = 0;
    recorder.chunks = [];
    recorder.processor.onaudioprocess = event => recorder.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    recorder.source.connect(recorder.processor);
    recorder.processor.connect(recorder.gain);
    recorder.gain.connect(recorder.context.destination);
    recorder.startedAt = Date.now();
    recorder.timer = setInterval(updateRecordingUi, 500);
    updateRecordingUi();
  } catch (error) {
    setMessage("new-message", `마이크 권한을 확인해 주세요: ${error.message}`);
  }
}

function updateRecordingUi() {
  const seconds = Math.floor((Date.now() - recorder.startedAt) / 1000);
  const time = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  $("record-message").textContent = `● 녹음 중 ${time}`;
  $("record-button").textContent = "■ 녹음 종료 및 변환";
}

async function stopRecording() {
  clearInterval(recorder.timer);
  recorder.processor.disconnect();
  recorder.source.disconnect();
  recorder.gain.disconnect();
  recorder.stream.getTracks().forEach(track => track.stop());
  const sampleRate = recorder.context.sampleRate;
  await recorder.context.close();
  const blob = encodeWav(recorder.chunks, sampleRate);
  recorder = { stream: null, context: null, source: null, processor: null, gain: null, chunks: [], startedAt: null, timer: null };
  $("record-message").textContent = "녹음 파일을 변환하고 있습니다.";
  $("record-button").textContent = "● 녹음 시작";
  await uploadAudio(new File([blob], `noting-record-${Date.now()}.wav`, { type: "audio/wav" }));
}

function encodeWav(chunks, sampleRate) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index));
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  chunks.forEach(chunk => chunk.forEach(sample => {
    const value = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
    offset += 2;
  }));
  return new Blob([buffer], { type: "audio/wav" });
}

async function openTranscript(id) {
  if (currentTranscriptId !== id) detailReturnPage = currentPage;
  currentTranscriptId = id;
  toggleSidebar(false);
  ["dashboard-view", "all-meetings-view", "tasks-view", "archive-view"].forEach(viewId => $(viewId).classList.add("hidden"));
  $("meeting-detail").classList.remove("hidden");
  $("page-header-label").textContent = "MEETING";
  $("workspace-caption").textContent = "회의 상세 및 AI 요약";
  $("detail-title").textContent = "회의록을 불러오는 중입니다.";
  $("detail-meta").textContent = "";
  $("detail-content").value = "";
  $("detail-summary").innerHTML = '<div class="analysis-loading"><span class="spinner"></span>분석 결과를 확인하고 있습니다.</div>';
  $("detail-tasks").innerHTML = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
  try {
    const data = await (await api(`/transcripts/${id}/tasks`)).json();
    let scheduleData = { change_candidates: [] };
    if (data.summary) {
      try {
        scheduleData = await (await api(`/transcripts/${id}/schedule-change-candidates`)).json();
      } catch (_) {
        // The detail itself remains usable if change detection is unavailable.
      }
    }
    renderMeetingDetail(data, scheduleData);
    if (data.analysis_status === "pending") await startAutoAnalysis(id);
    else if (data.analysis_status === "processing") pollAnalysis(id);
  } catch (error) {
    $("detail-title").textContent = `회의록 #${id}`;
    $("detail-summary").innerHTML = `<div class="analysis-error">${escapeHtml(error.message)}</div>`;
  }
}

function renderMeetingDetail(data, scheduleData = { change_candidates: [] }) {
  const status = data.analysis_status || (data.summary ? "completed" : "pending");
  $("detail-title").textContent = data.title || `회의록 #${data.id}`;
  $("title-input").value = data.title || `회의록 #${data.id}`;
  $("detail-meta").innerHTML = `
    <span>회의록 #${data.id}</span>
    <span>${escapeHtml(data.department || me?.department || "")}</span>
    <span>${escapeHtml(formatDate(data.created_at, true))}</span>
    <span>${data.title_is_manual ? "사용자 수정 제목" : "AI 자동 제목"}</span>
  `;
  $("detail-content").value = data.masked_content || "";
  const state = $("detail-analysis-state");
  state.textContent = analysisLabel(status);
  state.className = `status-pill ${status === "completed" ? "" : status}`.trim();
  if (status === "completed" && data.summary) {
    $("detail-summary").textContent = data.summary;
  } else if (status === "failed") {
    $("detail-summary").innerHTML = `<div class="analysis-error">자동 분석에 실패했습니다.<br />${escapeHtml(data.analysis_error || "LLM 서버 상태를 확인한 뒤 다시 시도해 주세요.")}</div><button class="button ghost compact" style="margin-top:10px" type="button" onclick="startAutoAnalysis(${data.id})">분석 다시 시도</button>`;
  } else {
    $("detail-summary").innerHTML = '<div class="analysis-loading"><span class="spinner"></span>AI가 제목·요약·업무와 RAG 검색 인덱스를 만들고 있습니다.<br />이 화면을 벗어나도 분석은 계속됩니다.</div>';
  }
  renderDetailTasks(data.id, data.tasks || []);
  renderScheduleChanges(data.id, scheduleData.change_candidates || []);
}

function renderDetailTasks(transcriptId, tasks) {
  $("detail-task-count").textContent = `${tasks.length}개`;
  if (!tasks.length) {
    $("detail-tasks").innerHTML = '<div class="empty-state">추출된 업무가 없습니다.</div>';
    return;
  }
  $("detail-tasks").innerHTML = tasks.map(task => `
    <div class="detail-task ${task.status === "완료" ? "done" : ""}">
      <button class="event-check ${task.status === "완료" ? "done" : ""}" type="button" onclick="updateTaskStatus(${transcriptId},${task.id},'${task.status === "완료" ? "대기" : "완료"}',true)">✓</button>
      <div class="detail-task-content"><b>${escapeHtml(task.task || "업무 항목")}</b><small>${escapeHtml(task.assignee || "담당 미지정")} · ${escapeHtml(task.due || "기한 미정")}${task.request ? ` · ${escapeHtml(task.request)}` : ""}</small></div>
      <select class="status-select" aria-label="업무 상태" onchange="updateTaskStatus(${transcriptId},${task.id},this.value,true)">
        ${["대기", "진행중", "완료"].map(status => `<option value="${status}" ${task.status === status ? "selected" : ""}>${status}</option>`).join("")}
      </select>
    </div>
  `).join("");
}

function renderScheduleChanges(transcriptId, changes) {
  $("detail-changes-section").classList.toggle("hidden", !changes.length);
  $("detail-changes").innerHTML = changes.map(change => `
    <div class="schedule-change">${escapeHtml(change.task.task)}<br /><b>${escapeHtml(change.previous_task.due)} → ${escapeHtml(change.task.due)}</b><button type="button" onclick="confirmScheduleChange(${transcriptId},${change.task.id},${change.previous_task.id})">이 일정 변경으로 확정</button></div>
  `).join("");
}

async function startAutoAnalysis(id) {
  try {
    await api(`/transcripts/${id}/analysis/start`, { method: "POST" });
    if (currentTranscriptId === id) {
      $("detail-analysis-state").textContent = "분석 중";
      $("detail-analysis-state").className = "status-pill processing";
      $("detail-summary").innerHTML = '<div class="analysis-loading"><span class="spinner"></span>백그라운드에서 회의를 분석하고 있습니다.<br />완료되면 이 영역이 자동으로 갱신됩니다.</div>';
    }
    pollAnalysis(id);
  } catch (error) {
    showToast(`자동 분석을 시작하지 못했습니다: ${error.message}`, "error");
    if (currentTranscriptId === id) {
      $("detail-summary").innerHTML = `<div class="analysis-error">${escapeHtml(error.message)}</div>`;
    }
  }
}

function pollAnalysis(id, attempt = 0) {
  if (analysisPollId) clearTimeout(analysisPollId);
  if (attempt > 240) {
    showToast("분석이 오래 걸리고 있습니다. 잠시 후 회의를 다시 열어 확인해 주세요.", "error");
    if (currentTranscriptId === id) {
      $("detail-summary").innerHTML = `<div class="analysis-error">분석 상태가 오래 갱신되지 않았습니다. 서버가 분석 도중 재시작됐을 수 있습니다.</div><button class="button ghost compact" style="margin-top:10px" type="button" onclick="startAutoAnalysis(${id})">분석 작업 다시 시작</button>`;
    }
    return;
  }
  analysisPollId = setTimeout(async () => {
    try {
      const data = await (await api(`/transcripts/${id}/tasks`)).json();
      const status = data.analysis_status || (data.summary ? "completed" : "pending");
      if (status === "completed" || status === "failed") {
        await refreshDashboard();
        if (currentTranscriptId === id) await openTranscript(id);
        showToast(status === "completed" ? "회의 분석과 RAG 인덱싱이 완료되었습니다." : "회의 분석에 실패했습니다.", status === "failed" ? "error" : "");
        return;
      }
      if (currentTranscriptId === id) renderMeetingDetail(data);
      pollAnalysis(id, attempt + 1);
    } catch (error) {
      if (attempt < 3) pollAnalysis(id, attempt + 1);
      else showToast(`분석 상태를 확인하지 못했습니다: ${error.message}`, "error");
    }
  }, 1500);
}

async function saveDetailContent() {
  if (!currentTranscriptId) return;
  const button = $("detail-save");
  button.disabled = true;
  button.textContent = "저장 중...";
  try {
    const data = await (await api(`/transcripts/${currentTranscriptId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: $("detail-content").value }),
    })).json();
    $("detail-content").value = data.masked_content;
    showToast("수정 내용을 저장했습니다. 새 분석을 시작합니다.");
    await startAutoAnalysis(currentTranscriptId);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "수정 내용 저장";
  }
}

function toggleDetailMenu() {
  $("detail-menu").classList.toggle("hidden");
}

function showTitleEditor() {
  $("detail-menu").classList.add("hidden");
  $("title-edit").classList.remove("hidden");
  $("title-input").focus();
}

function hideTitleEditor() {
  $("title-edit").classList.add("hidden");
}

async function saveTitle() {
  const title = $("title-input").value.trim();
  if (!currentTranscriptId || !title) return;
  try {
    await api(`/transcripts/${currentTranscriptId}/title`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    hideTitleEditor();
    await refreshDashboard();
    await openTranscript(currentTranscriptId);
    showToast("회의 제목을 수정했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function updateTaskStatus(transcriptId, taskId, status, reopen = false) {
  try {
    await api(`/transcripts/${transcriptId}/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    await refreshDashboard();
    if (reopen && currentTranscriptId === transcriptId) await openTranscript(transcriptId);
    else if (currentPage === "tasks") renderTasksPage();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function confirmScheduleChange(transcriptId, taskId, previousTaskId) {
  try {
    await api(`/transcripts/${transcriptId}/tasks/${taskId}/schedule-changes/${previousTaskId}/confirm`, { method: "POST" });
    await refreshDashboard();
    await openTranscript(transcriptId);
    showToast("이전 업무를 변경됨으로 연결했습니다.");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function askSuggested(question, scope) {
  $(`qa-${scope}-input`).value = question;
  askMeetingAssistant(null, scope);
}

async function askMeetingAssistant(event, scope = "dashboard") {
  event?.preventDefault();
  const input = $(`qa-${scope}-input`);
  const submit = $(`qa-${scope}-submit`);
  const messages = $(`qa-${scope}-messages`);
  const question = input.value.trim();
  if (!question) return;
  messages.insertAdjacentHTML("beforeend", `<div class="chat-bubble user">${escapeHtml(question)}</div>`);
  input.value = "";
  submit.disabled = true;
  const loading = document.createElement("div");
  loading.className = "chat-bubble ai";
  loading.innerHTML = '<div class="analysis-loading"><span class="spinner"></span>회의 근거를 검색하고 있습니다.</div>';
  messages.appendChild(loading);
  messages.scrollTop = messages.scrollHeight;
  try {
    const data = await (await api("/transcripts/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    })).json();
    const sources = (data.sources || []).map(source => `
      <button class="chat-source" type="button" onclick="openTranscript(${source.id})">
        회의록 #${source.id}${source.chunk_index === null || source.chunk_index === undefined ? "" : ` · 본문 ${source.chunk_index + 1}`} · 유사도 ${source.similarity}<br />
        ${escapeHtml(source.content || source.summary || "근거 내용 없음")}
      </button>
    `).join("");
    loading.innerHTML = `${escapeHtml(data.answer)}${sources}`;
  } catch (error) {
    loading.classList.add("error");
    loading.textContent = error.message;
  } finally {
    submit.disabled = false;
    messages.scrollTop = messages.scrollHeight;
  }
}

async function downloadPdf(id) {
  if (!id) return;
  $("detail-menu").classList.add("hidden");
  try {
    const response = await api(`/transcripts/${id}/report.pdf`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `noting-report-${id}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    showToast(`PDF를 만들지 못했습니다: ${error.message}`, "error");
  }
}

async function viewPii(id) {
  $("detail-menu").classList.add("hidden");
  try {
    const items = await (await api(`/transcripts/${id}/pii`)).json();
    const rows = items.map(item => `<tr><td>${escapeHtml(item.pii_type)}</td><td>${escapeHtml(item.original_value)}</td></tr>`).join("")
      || '<tr><td colspan="2">저장된 원본이 없습니다.</td></tr>';
    showResult("개인정보 원본", `<table class="result-table"><thead><tr><th>유형</th><th>원본 값</th></tr></thead><tbody>${rows}</tbody></table>`);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function showResult(title, html) {
  $("result-title").textContent = title;
  $("result-content").innerHTML = html;
  $("result-modal").classList.remove("hidden");
}

function hideResult() {
  $("result-modal").classList.add("hidden");
}

async function openAdmin() {
  toggleSidebar(false);
  $("admin-modal").classList.remove("hidden");
  await loadPending();
}

function closeAdmin() {
  $("admin-modal").classList.add("hidden");
}

async function loadPending() {
  const box = $("pending-list");
  box.innerHTML = '<div class="empty-state">승인 요청을 확인하고 있습니다.</div>';
  try {
    const items = await (await api("/users/pending")).json();
    box.innerHTML = items.length ? items.map(user => `
      <div class="admin-row"><div><b>${escapeHtml(user.username)}</b><small>${escapeHtml(user.department)} · ${escapeHtml(user.role)}</small></div><div><button type="button" onclick="decide(${user.id},'approve')">승인</button><button class="reject" type="button" onclick="decide(${user.id},'reject')">거절</button></div></div>
    `).join("") : '<div class="empty-state">대기 중인 가입 요청이 없습니다.</div>';
  } catch (error) {
    box.innerHTML = `<div class="analysis-error">${escapeHtml(error.message)}</div>`;
  }
}

async function decide(id, action) {
  try {
    await api(`/users/${id}/${action}`, { method: "POST" });
    await loadPending();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function restoreSession() {
  if (!token) return;
  try {
    await loadMe();
  } catch (_) {
    sessionStorage.removeItem("noting_token");
    token = null;
    me = null;
    $("app-view").classList.add("hidden");
    $("auth-view").classList.remove("hidden");
  }
}

restoreSession();
