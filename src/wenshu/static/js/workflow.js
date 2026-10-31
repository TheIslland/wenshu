/* 研究流程：三列看板、模板、门禁、任务增删与状态流转。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  const COLUMNS = [
    { key: "todo", label: "待办", aliases: ["todo", "pending", "inbox"] },
    { key: "doing", label: "进行中", aliases: ["doing", "in_progress", "in-progress", "active"] },
    { key: "done", label: "完成", aliases: ["done", "completed", "complete"] },
  ];
  const TYPE_LABELS = { citation: "未核引", style: "高风险段未处理", gap: "未解决 gaps" };

  let panelEl = null;
  let bound = false;
  let tasks = [];
  let busy = false;

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;
    const apply = $("#apply-template");
    if (apply) apply.addEventListener("click", applyTemplate);
    const add = $("#add-task");
    if (add) add.addEventListener("click", toggleAddForm);
    const submit = $("#task-add-submit");
    if (submit) submit.addEventListener("click", addTask);
    const cancel = $("#task-add-cancel");
    if (cancel) cancel.addEventListener("click", () => toggleAddForm(false));
    const refresh = $("#refresh-tasks");
    if (refresh) refresh.addEventListener("click", refreshAll);
    const title = $("#task-title");
    if (title) {
      title.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          addTask();
        }
      });
    }
    const kanban = $("#kanban");
    if (kanban) kanban.addEventListener("click", onBoardClick);
    const gateBox = $("#gate-blockers");
    if (gateBox) gateBox.addEventListener("click", (event) => {
      const missed = event.target.closest("[data-gate-missing]");
      if (missed) loadGate();
    });
    refreshAll();
  }

  async function refreshAll() {
    await Promise.all([loadTasks(), loadGate()]);
  }

  async function loadTasks() {
    const board = $("#kanban");
    if (!board) return;
    W.loading(board, "正在加载流程…");
    try {
      const data = await api.get("/api/tasks?project_id=" + W.projectId);
      tasks = Array.isArray(data) ? data : Array.isArray(data && data.tasks) ? data.tasks : [];
      renderBoard();
    } catch (error) {
      W.showError(board, error, { retry: loadTasks });
    }
  }

  async function loadGate() {
    const status = $("#gate-status");
    const box = $("#gate-blockers");
    if (status) {
      status.textContent = "门禁检查中…";
      status.className = "gate-status muted";
    }
    if (box) box.innerHTML = "";
    try {
      const data = await api.get("/api/workflow/gate?project_id=" + W.projectId);
      const blockers = Array.isArray(data && data.blockers) ? data.blockers : [];
      const ok = !!(data && data.ok);
      if (status) {
        status.textContent = ok
          ? "门禁：通过，可导出"
          : "门禁：" + blockers.length + " 项未通过（可强制导出但需确认）";
        status.className = "gate-status " + (ok ? "ok" : "bad");
      }
      if (box && blockers.length) {
        const groups = groupBlockers(blockers);
        box.innerHTML =
          '<div class="banner danger"><div><strong>导出前未通过：</strong>' +
          esc(gateSummary(blockers)) +
          "</div></div>" +
          '<ul class="gate-list">' +
          groups
            .map(
              (group) =>
                "<li>" +
                esc(group.label + (group.count > 1 ? "（" + group.count + " 项）" : "") +
                  (group.message ? "：" + group.message : "")) +
                "</li>"
            )
            .join("") +
          "</ul>";
      }
    } catch (error) {
      const info = W.describeError(error);
      if (status) {
        status.textContent = info.missing ? "门禁模块未就绪" : "门禁检查失败：" + info.message;
        status.className = "gate-status muted";
      }
      if (box) {
        box.innerHTML =
          '<p class="hint">' + esc(info.missing ? "门禁接口未接上，导出前请人工核对未核引与高风险段。" : info.message) +
          ' <button class="link" type="button" data-gate-missing>重试</button></p>';
      }
    }
  }

  function gateSummary(blockers) {
    const counts = {};
    blockers.forEach((blocker) => {
      const type = (blocker && blocker.type) || "其它";
      counts[type] = (counts[type] || 0) + 1;
    });
    return Object.entries(counts)
      .map(([type, count]) => (TYPE_LABELS[type] || type) + " " + count + " 项")
      .join(" · ");
  }

  function groupBlockers(blockers) {
    const groups = new Map();
    blockers.forEach((blocker) => {
      const label = TYPE_LABELS[blocker && blocker.type] || (blocker && blocker.type) || "问题";
      const message =
        (blocker && (blocker.message || blocker.title || blocker.detail)) ||
        (blocker && Array.isArray(blocker.ref_ids) && blocker.ref_ids.length
          ? "文献 #" + blocker.ref_ids.join("、")
          : "");
      const key = label + "|" + message;
      const group = groups.get(key) || { label, message, count: 0 };
      group.count += 1;
      groups.set(key, group);
    });
    return Array.from(groups.values());
  }

  function statusKey(status) {
    const value = String(status || "").toLowerCase();
    const column = COLUMNS.find((item) => item.aliases.includes(value));
    return column ? column.key : "todo";
  }

  function renderBoard() {
    const board = $("#kanban");
    if (!board) return;
    if (!tasks.length) {
      board.innerHTML = "";
      W.empty(
        board,
        "还没有任务。",
        "套用一个模板（开题 / 论文 / 投稿），或新建第一条任务。",
        '<button class="btn" type="button" data-board-action="template">套用「论文」模板</button>' +
          '<button class="btn ghost" type="button" data-board-action="add">新建任务</button>'
      );
      board.querySelectorAll("[data-board-action]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.dataset.boardAction === "template") applyTemplate("paper");
          else toggleAddForm(true);
        });
      });
      return;
    }
    board.innerHTML = COLUMNS.map((column) => {
      const items = tasks
        .filter((task) => statusKey(task.status) === column.key)
        .sort((a, b) => (Number(a.sort) || 0) - (Number(b.sort) || 0) || (a.id || 0) - (b.id || 0));
      return (
        '<div class="kanban-col" data-col="' + column.key + '">' +
        '<div class="kanban-head"><h3>' + column.label + "</h3>" +
        '<span class="kanban-count">' + items.length + "</span></div>" +
        (items.length
          ? items.map(taskCard).join("")
          : '<div class="task-empty">拖不了也没关系，用卡片上的箭头挪。</div>') +
        "</div>"
      );
    }).join("");
  }

  function taskCard(task) {
    const status = statusKey(task.status);
    const index = COLUMNS.findIndex((column) => column.key === status);
    const meta = [task.due ? "截止 " + window.fmtDate(task.due) : "", task.notes || ""]
      .filter(Boolean)
      .join(" · ");
    return (
      '<article class="task' + (status === "done" ? " done" : "") + '" data-task-id="' + task.id + '">' +
      '<div class="task-head"><span class="task-title">' + esc(task.title || "（未命名任务）") + "</span>" +
      (task.stage ? '<span class="task-stage">' + esc(task.stage) + "</span>" : "") +
      "</div>" +
      (meta ? '<div class="task-meta">' + esc(meta) + "</div>" : "") +
      '<div class="task-actions">' +
      '<button class="btn ghost" type="button" data-task-action="move" data-task-id="' + task.id +
      '" data-dir="-1"' + (index === 0 ? " disabled" : "") + " title=\"移到上一列\">←</button>" +
      '<button class="btn ghost" type="button" data-task-action="move" data-task-id="' + task.id +
      '" data-dir="1"' + (index === COLUMNS.length - 1 ? " disabled" : "") + " title=\"移到下一列\">→</button>" +
      '<button class="btn ghost" type="button" data-task-action="delete" data-task-id="' + task.id + '">删除</button>' +
      "</div></article>"
    );
  }

  async function onBoardClick(event) {
    const button = event.target.closest("[data-task-action]");
    if (!button || !panelEl.contains(button)) return;
    const id = Number(button.dataset.taskId);
    const action = button.dataset.taskAction;
    if (action === "move") moveTask(id, Number(button.dataset.dir));
    else if (action === "delete") deleteTask(id);
  }

  async function moveTask(id, direction) {
    const task = tasks.find((item) => item.id === id);
    if (!task) return;
    const index = COLUMNS.findIndex((column) => column.key === statusKey(task.status));
    const next = index + direction;
    if (next < 0 || next >= COLUMNS.length) return;
    const status = COLUMNS[next].key;
    try {
      const updated = await api.patch("/api/tasks/" + id, { status });
      Object.assign(task, updated && updated.id ? updated : { status });
      renderBoard();
      toast("已移到「" + COLUMNS[next].label + "」。", "ok");
      loadGate();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function deleteTask(id) {
    const task = tasks.find((item) => item.id === id);
    if (!task) return;
    const ok = window.confirm("删除任务「" + (task.title || "") + "」？");
    if (!ok) return;
    try {
      await api.del("/api/tasks/" + id);
      tasks = tasks.filter((item) => item.id !== id);
      renderBoard();
      toast("任务已删除。", "ok");
      loadGate();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function toggleAddForm(force) {
    const form = $("#task-add-form");
    if (!form) return;
    const show = typeof force === "boolean" ? force : form.classList.contains("hidden");
    form.classList.toggle("hidden", !show);
    if (show) {
      const title = $("#task-title");
      if (title) title.focus();
    }
  }

  async function addTask() {
    const titleNode = $("#task-title");
    const title = titleNode ? titleNode.value.trim() : "";
    if (!title) {
      toast("先写任务标题。", "error");
      return;
    }
    const stageNode = $("#task-stage");
    const submit = $("#task-add-submit");
    if (submit) submit.disabled = true;
    try {
      const task = await api.post("/api/tasks", {
        project_id: W.projectId,
        title,
        stage: stageNode ? stageNode.value : "写作",
      });
      if (task && task.id) tasks.push(task);
      titleNode.value = "";
      toggleAddForm(false);
      renderBoard();
      toast("任务已添加。", "ok");
      loadGate();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function applyTemplate(forceTemplate) {
    if (busy) return;
    const select = $("#workflow-template");
    const template = typeof forceTemplate === "string" ? forceTemplate : select ? select.value : "paper";
    if (tasks.length) {
      const ok = window.confirm("套用模板会追加任务，不会删除已有任务。继续？");
      if (!ok) return;
    }
    busy = true;
    const button = $("#apply-template");
    if (button) button.disabled = true;
    try {
      const result = await api.post("/api/workflow/template", {
        project_id: W.projectId,
        template,
      });
      const added = Array.isArray(result)
        ? result.length
        : Number(result && result.added) || (result && Array.isArray(result.tasks) ? result.tasks.length : 0);
      toast("模板已套用" + (added ? "：" + added + " 条任务" : "") + "。", "ok");
      await refreshAll();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  W.views.workflow = {
    mount,
    async show() {
      await refreshAll();
    },
  };
})();
