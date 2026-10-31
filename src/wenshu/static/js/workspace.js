/* Workspace shell: tabs, health probe, writing editor, cross-tab diff handoff.
 * Loaded last; every tab module registers itself on window.Wenshu.views.
 */
(function () {
  const root = document.getElementById("workspace");
  if (!root) return;

  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};

  const projectId = Number(root.dataset.projectId);
  const projectName = root.dataset.projectName || "";
  const demo = root.dataset.demo === "1";
  const $ = (selector, scope) => (scope || root).querySelector(selector);
  const $$ = (selector, scope) => Array.from((scope || root).querySelectorAll(selector));
  const esc = window.escapeHtml;
  const toast = window.toast;

  const state = {
    projectId,
    projectName,
    demo,
    documents: [],
    current: null,
    health: null,
    llmConfigured: null,
    activeTab: "overview",
    mounted: {},
    mounting: {},
    dirty: false,
    saving: false,
    conflict: false,
    editTarget: null,
  };
  W.state = state;
  W.projectId = projectId;
  W.projectName = projectName;
  W.demo = demo;
  W.$ = $;
  W.$$ = $$;
  W.esc = esc;
  W.toast = toast;
  W.fmt = window.fmtDate;

  /* ---------------- shared helpers ---------------- */

  W.loading = function (node, label) {
    if (!node) return;
    node.innerHTML =
      '<div class="loading"><span class="spinner" aria-hidden="true"></span>' +
      esc(label || "正在加载…") +
      "</div>";
  };

  W.describeError = function (error) {
    const status = error && error.status;
    const code = error && error.code;
    const message = (error && error.message) || "请求失败，请稍后重试。";
    const missing =
      code === "module_unavailable" ||
      status === 501 ||
      (status === 404 && /not found/i.test(message));
    const noLlm = code === "llm_not_configured" || code === "llm_unavailable" || status === 503;
    let title = "加载失败";
    let detail = message;
    let hint = "";
    if (missing) {
      title = "模块未就绪";
      hint = "前端已按契约就位；后端模块上线后点重试即可，不影响其它标签页。";
    } else if (noLlm) {
      title = "模型未配置 / 不可用";
      hint = "规则体检、检索和文献库仍可用；润色、调段、LLM 复审需要先在设置里配置模型。";
    }
    return { missing, noLlm, title, detail, hint, message, status: status || 0 };
  };

  W.showError = function (node, error, options = {}) {
    if (!node) return;
    const info = W.describeError(error);
    if (!options.silent) toast(info.message, "error");
    node.innerHTML =
      '<div class="empty error-state">' +
      '<p class="error-title">' + esc(info.title) + "</p>" +
      "<p>" + esc(info.detail) + "</p>" +
      (info.hint ? '<p class="muted">' + esc(info.hint) + "</p>" : "") +
      '<div class="empty-actions">' +
      (info.noLlm ? '<a class="btn" href="/settings">去设置模型</a>' : "") +
      '<button class="btn" type="button" data-retry>重试</button>' +
      "</div></div>";
    const retry = node.querySelector("[data-retry]");
    if (retry && options.retry) retry.addEventListener("click", options.retry);
  };

  W.load = async function (node, fetcher, render, options = {}) {
    if (node) W.loading(node, options.loading || "正在加载…");
    try {
      const data = await fetcher();
      if (render) render(data);
      return data;
    } catch (error) {
      W.showError(node, error, { retry: options.retry });
      return null;
    }
  };

  W.empty = function (node, title, hint, actionsHtml) {
    if (!node) return;
    node.innerHTML =
      '<div class="empty">' +
      (title ? "<p>" + esc(title) + "</p>" : "") +
      (hint ? '<p class="muted">' + esc(hint) + "</p>" : "") +
      (actionsHtml || "") +
      "</div>";
  };

  W.copy = async function (text) {
    if (!text) return false;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
        toast("已复制到剪贴板。", "ok");
        return true;
      }
    } catch (_) { /* fall through */ }
    toast("复制失败，请手动选择文本。", "error");
    return false;
  };

  W.llmHintHtml = function () {
    if (state.llmConfigured !== false) return "";
    return (
      '<div class="no-llm">还没有配置 LLM：规则体检、检索、文献库可离线用；' +
      "润色 / 调段 / LLM 复审需要模型。<a href=\"/settings\">去设置</a></div>"
    );
  };

  W.refreshLlmHints = function () {
    ["#llm-hint-style", "#llm-hint-polish", "#llm-hint-paragraphs"].forEach((selector) => {
      const node = $(selector);
      if (node) node.innerHTML = W.llmHintHtml();
    });
    const toggle = $("#style-use-llm");
    if (toggle) {
      toggle.disabled = state.llmConfigured === false;
      toggle.title = state.llmConfigured === false ? "需要先在设置里配置 LLM" : "";
      if (state.llmConfigured === false) toggle.checked = false;
    }
  };

  W.setCounts = function (counts = {}) {
    if (typeof counts.documents === "number") {
      const meta = $("#meta-docs");
      if (meta) meta.textContent = counts.documents + " 篇文档";
      const stat = $("#stat-documents");
      if (stat) stat.textContent = counts.documents;
    }
    if (typeof counts.refs === "number") {
      const meta = $("#meta-refs");
      if (meta) meta.textContent = counts.refs + " 本文献";
      const stat = $("#stat-refs");
      if (stat) stat.textContent = counts.refs;
    }
  };

  W.gapsHtml = function (gaps) {
    if (!Array.isArray(gaps) || !gaps.length) return "";
    return (
      '<div class="gaps"><h4>缺证据 / 待补（不会替你编）</h4><ul>' +
      gaps.map((gap) => "<li>" + esc(String(gap)) + "</li>").join("") +
      "</ul></div>"
    );
  };

  W.warningsHtml = function (warnings) {
    if (!Array.isArray(warnings) || !warnings.length) return "";
    return (
      '<div class="warnings"><ul>' +
      warnings.map((warning) => "<li>" + esc(String(warning)) + "</li>").join("") +
      "</ul></div>"
    );
  };

  function coarseDiff(original, revised) {
    const ops = [];
    let start = 0;
    const minLength = Math.min(original.length, revised.length);
    while (start < minLength && original[start] === revised[start]) start += 1;
    let endOriginal = original.length;
    let endRevised = revised.length;
    while (
      endOriginal > start &&
      endRevised > start &&
      original[endOriginal - 1] === revised[endRevised - 1]
    ) {
      endOriginal -= 1;
      endRevised -= 1;
    }
    if (start) ops.push({ op: "equal", text: original.slice(0, start) });
    if (endOriginal > start) ops.push({ op: "delete", text: original.slice(start, endOriginal) });
    if (endRevised > start) ops.push({ op: "insert", text: revised.slice(start, endRevised) });
    if (endOriginal < original.length) ops.push({ op: "equal", text: original.slice(endOriginal) });
    return ops;
  }

  function normalizeDiffOp(op) {
    const value = String(op == null ? "equal" : op).toLowerCase();
    if (value === "insert" || value === "+" || value === "add") return "insert";
    if (value === "delete" || value === "-" || value === "del") return "delete";
    return "equal";
  }

  W.diffHtml = function (data) {
    let ops = Array.isArray(data && data.diff) ? data.diff : [];
    if (!ops.length) {
      const original = String((data && (data.original || data.source_text)) || "");
      const revised = String((data && (data.revised || data.result_text)) || "");
      ops = coarseDiff(original, revised);
    }
    return ops
      .filter((op) => op && op.text != null && op.text !== "")
      .map((op) => {
        const kind = normalizeDiffOp(op.op);
        const text = esc(String(op.text));
        if (kind === "insert") return "<ins>" + text + "</ins>";
        if (kind === "delete") return "<del>" + text + "</del>";
        return '<span class="same">' + text + "</span>";
      })
      .join("");
  };

  W.renderRewrite = function (container, data, options = {}) {
    if (!container) return "";
    data = data || {};
    const original = String(data.original != null ? data.original : options.text || "");
    const revised = String(data.revised != null ? data.revised : data.result_text || "");
    const before = original.length;
    const after = revised.length;
    const delta = before ? Math.round(((after - before) / before) * 100) : 0;
    const metaParts = [];
    if (data.provider || data.model) {
      metaParts.push(esc([data.provider, data.model].filter(Boolean).join(" · ")));
    }
    if (data.mode) metaParts.push("模式 " + esc(data.mode));
    metaParts.push(before + " → " + after + " 字（" + (delta >= 0 ? "+" : "") + delta + "%）");
    const ops = Array.isArray(data.ops) ? data.ops : [];
    const actions =
      options.actions === false
        ? ""
        : '<div class="diff-actions">' +
          '<button class="btn primary" type="button" data-rewrite-action="accept">接受并写回</button>' +
          '<button class="btn ghost" type="button" data-rewrite-action="reject">拒绝</button>' +
          '<button class="btn ghost" type="button" data-rewrite-action="retry">再来一版</button>' +
          '<button class="btn ghost" type="button" data-rewrite-action="copy">复制</button>' +
          "</div>";
    container.innerHTML =
      '<div class="rewrite-meta">' + metaParts.join("<span>·</span>") + "</div>" +
      '<div class="diff-legend"><span><i class="lg-same"></i>保留</span>' +
      '<span><i class="lg-add"></i>新增</span><span><i class="lg-del"></i>删除</span></div>' +
      '<div class="diff" data-diff>' + W.diffHtml(data) + "</div>" +
      actions +
      (ops.length
        ? '<div class="ops"><h4>修改理由</h4><ol class="ops-list">' +
          ops.map((op) => "<li>" + esc(describeOp(op)) + "</li>").join("") +
          "</ol></div>"
        : "") +
      W.gapsHtml(data.gaps) +
      W.warningsHtml(data.warnings);
    container._wenshuRevised = revised;
    return revised;
  };

  function describeOp(op) {
    if (op == null) return "";
    if (typeof op === "string") return op;
    if (typeof op === "object") {
      if (Array.isArray(op.items) && (op.action === "anchors" || op.action === "preserved")) {
        return (op.action === "anchors" ? "锚点" : "保留") + "：" + op.items.join("、");
      }
      if (op.reason || op.note || op.desc || op.description) {
        return String(op.reason || op.note || op.desc || op.description);
      }
      if (op.op || op.type || op.action) {
        return String(op.op || op.type || op.action) + (op.text ? "：" + op.text : "");
      }
      try {
        return JSON.stringify(op);
      } catch (_) {
        return String(op);
      }
    }
    return String(op);
  }

  W.bindRewriteActions = function (container, handlers = {}) {
    if (!container || container._wenshuBound) return;
    container._wenshuBound = true;
    container.addEventListener("click", (event) => {
      const button = event.target.closest("[data-rewrite-action]");
      if (!button || !container.contains(button)) return;
      const action = button.dataset.rewriteAction;
      const revised = container._wenshuRevised;
      if (action === "accept" && handlers.accept) handlers.accept(revised);
      else if (action === "reject" && handlers.reject) handlers.reject();
      else if (action === "retry" && handlers.retry) handlers.retry();
      else if (action === "copy") W.copy(revised);
    });
  };

  W.setEditTarget = function (target) {
    state.editTarget = target || null;
  };

  W.targetForText = function (text, hintStart) {
    if (!text || !state.current) return null;
    const editor = $("#editor");
    if (!editor) return null;
    const value = editor.value || "";
    let index = -1;
    if (typeof hintStart === "number" && value.slice(hintStart, hintStart + text.length) === text) {
      index = hintStart;
    }
    if (index < 0) index = value.indexOf(text);
    if (index < 0) return null;
    return {
      documentId: state.current.id,
      start: index,
      end: index + text.length,
      original: text,
    };
  };

  W.applyRevision = async function (revised, label) {
    if (!revised) return false;
    const target = state.editTarget;
    const current = state.current;
    const editor = $("#editor");
    if (
      target &&
      current &&
      editor &&
      target.documentId === current.id &&
      editor.value.slice(target.start, target.end) === target.original
    ) {
      const next = editor.value.slice(0, target.start) + revised + editor.value.slice(target.end);
      editor.value = next;
      state.editTarget = {
        documentId: current.id,
        start: target.start,
        end: target.start + revised.length,
        original: revised,
      };
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      toast("已写回写作页，正在保存。", "ok");
      try {
        if (W.saveNow) await W.saveNow({ silent: true });
        if (W.snapshotDocument) await W.snapshotDocument(label || "接受改写");
      } catch (error) {
        toast(error.message, "error");
      }
      return true;
    }
    await W.copy(revised);
    toast("找不到原文位置，已复制；请手动粘贴到写作页。", "ok");
    return false;
  };

  W.useEditorTarget = function () {
    const target = W.currentTarget();
    if (!target) {
      toast("写作页还没有打开文档。", "error");
      return null;
    }
    W.setEditTarget({
      documentId: target.documentId,
      start: target.start,
      end: target.end,
      original: target.text,
    });
    return target.text;
  };

  W.sendText = async function (tabName, text, target) {
    if (!text) return;
    W.setEditTarget(target || null);
    await openTab(tabName);
    const view = W.views[tabName];
    if (view && view.setTarget) view.setTarget(text);
  };

  W.contextAround = function (size) {
    const target = state.editTarget;
    const editor = $("#editor");
    if (!target || !editor) return { before: "", after: "" };
    const span = typeof size === "number" ? size : 200;
    return {
      before: editor.value.slice(Math.max(0, target.start - span), target.start),
      after: editor.value.slice(target.end, target.end + span),
    };
  };

  /* Shared create/run/diff flow for 润色 and 调段. */
  W.createRewritePanel = function (panel, options) {
    const input = panel.querySelector(options.input);
    const runButton = panel.querySelector(options.run);
    const result = panel.querySelector(options.result);
    const modeNode = options.mode ? panel.querySelector(options.mode) : null;
    const loadSelection = options.loadSelection
      ? panel.querySelector(options.loadSelection)
      : null;
    let last = null;

    function setTarget(text) {
      if (input) input.value = text || "";
    }

    async function run() {
      const text = input ? input.value.trim() : "";
      if (!text) {
        toast("先贴一段文字，或在写作页选中段落后点「取当前段落」。", "error");
        return;
      }
      const target =
        state.editTarget && state.editTarget.original === text
          ? state.editTarget
          : W.targetForText(text);
      W.setEditTarget(target);
      if (result) W.loading(result, options.loading || "正在请求改写…");
      if (runButton) runButton.disabled = true;
      try {
        const body = options.buildBody(text, {
          mode: modeNode ? modeNode.value : "",
          target,
        });
        const data = await api.post(options.endpoint, body);
        last = data;
        if (result) W.renderRewrite(result, data, { text });
      } catch (error) {
        W.showError(result, error, { retry: run });
      } finally {
        if (runButton) runButton.disabled = false;
      }
    }

    if (runButton) runButton.addEventListener("click", run);
    if (loadSelection) {
      loadSelection.addEventListener("click", () => {
        const text = W.useEditorTarget();
        if (text) setTarget(text);
      });
    }
    if (result) {
      result.addEventListener("click", (event) => {
        const button = event.target.closest("[data-rewrite-action]");
        if (!button) return;
        const action = button.dataset.rewriteAction;
        if (action === "accept") {
          if (last) W.applyRevision(last.revised, options.acceptLabel || "接受改写");
        } else if (action === "reject") {
          result.innerHTML = "";
          last = null;
          toast("已拒绝，原文未动。", "ok");
        } else if (action === "retry") {
          run();
        } else if (action === "copy") {
          if (last) W.copy(last.revised);
        }
      });
    }
    return { setTarget, run };
  };

  /* ---------------- tabs ---------------- */

  const tabButtons = $$(".tab");
  const panels = {};
  tabButtons.forEach((button) => {
    panels[button.dataset.tab] = document.getElementById("panel-" + button.dataset.tab);
    button.addEventListener("click", () => openTab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      event.preventDefault();
      const index = tabButtons.indexOf(button);
      const next = tabButtons[(index + (event.key === "ArrowRight" ? 1 : -1) + tabButtons.length) % tabButtons.length];
      next.focus();
      openTab(next.dataset.tab);
    });
  });
  $$("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => openTab(button.dataset.goto));
  });

  function ensureMounted(name) {
    if (state.mounted[name]) return Promise.resolve();
    if (state.mounting[name]) return state.mounting[name];
    const view = W.views[name];
    if (!view || !view.mount) {
      state.mounted[name] = true;
      return Promise.resolve();
    }
    const panel = panels[name];
    state.mounting[name] = Promise.resolve()
      .then(() => view.mount(panel, { projectId, demo }))
      .then(() => {
        state.mounted[name] = true;
      })
      .finally(() => {
        delete state.mounting[name];
      });
    return state.mounting[name];
  }

  async function openTab(name) {
    if (!panels[name]) return;
    tabButtons.forEach((button) => {
      const on = button.dataset.tab === name;
      button.classList.toggle("active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
      button.tabIndex = on ? 0 : -1;
    });
    Object.entries(panels).forEach(([key, panel]) => {
      if (panel) panel.classList.toggle("active", key === name);
    });
    state.activeTab = name;
    try {
      history.replaceState(null, "", "#" + name);
    } catch (_) { /* file:// or blocked history */ }
    try {
      await ensureMounted(name);
      const view = W.views[name];
      if (view && view.show) await view.show(panels[name], { projectId, demo });
    } catch (error) {
      console.error(error);
      W.showError(panels[name], error, {});
    }
  }
  W.openTab = openTab;

  window.addEventListener("hashchange", () => {
    const name = (location.hash || "").replace("#", "");
    if (panels[name] && name !== state.activeTab) openTab(name);
  });

  /* ---------------- health ---------------- */

  async function refreshHealth() {
    const dot = $("#llm-dot");
    const label = $("#llm-status");
    const detail = $("#health-detail");
    const statLlm = $("#stat-llm");
    try {
      const health = await api.get("/api/health");
      state.health = health;
      state.llmConfigured = !!health.llm_configured;
      if (dot) dot.className = "status-dot " + (health.demo || health.llm_configured ? "ok" : "off");
      if (label) {
        if (health.demo) {
          label.textContent = "演示模式：AI 返回示例结果";
        } else if (health.llm_configured) {
          const model = [health.llm_provider, health.llm_model].filter(Boolean).join(" · ");
          label.textContent = "LLM 已配置" + (model ? "（" + model + "）" : "");
        } else {
          label.innerHTML = '未配置 LLM · 规则与文献功能可用 · <a href="/settings">去设置</a>';
        }
      }
      if (detail) {
        const tokenizer = health.fts_tokenizer ? "FTS " + health.fts_tokenizer : "FTS ?";
        detail.textContent = tokenizer + " · v" + (health.version || "0");
      }
      if (statLlm) {
        statLlm.textContent = health.demo
          ? "演示"
          : health.llm_configured
            ? health.llm_model || "已配置"
            : "未配置";
      }
      if (health.counts) {
        const counts = health.counts;
        if (typeof counts.documents === "number") W.setCounts({ documents: counts.documents });
        if (typeof health.counts.refs === "number") W.setCounts({ refs: counts.refs });
      }
      if (health.fts_tokenizer) {
        const ftsStat = $("#stat-fts");
        if (ftsStat) ftsStat.textContent = health.fts_tokenizer;
      }
    } catch (error) {
      state.llmConfigured = null;
      if (dot) dot.className = "status-dot off";
      if (label) label.textContent = "模型状态未知（/api/health 不可用）";
      if (statLlm) statLlm.textContent = "未知";
    }
    W.refreshLlmHints();
  }

  /* ---------------- writing ---------------- */

  const writing = {
    timer: null,
    paragraphTimer: null,
    bound: false,
  };

  function wordCountOf(text) {
    const cjk = (text.match(/[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]/g) || []).length;
    const latin = (text.match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g) || []).length;
    return cjk + latin;
  }

  function setSaveState(kind, text) {
    const badge = $("#autosave-state");
    const strip = $("#save-status");
    if (badge) {
      badge.dataset.state = kind || "";
      badge.textContent = text || "";
    }
    if (strip) strip.textContent = text || "";
  }

  function updateWordCount() {
    const editor = $("#editor");
    const node = $("#word-count");
    if (editor && node) node.textContent = wordCountOf(editor.value || "") + " 字";
  }

  function renderDocuments() {
    const list = $("#document-list");
    const count = $("#document-count");
    if (count) count.textContent = state.documents.length + " 篇";
    if (!list) return;
    if (!state.documents.length) {
      W.empty(
        list,
        "还没有文档。",
        "点下面「新建文档」开始。",
        '<button class="btn ghost" type="button" data-new-doc>新建文档</button>'
      );
      const button = list.querySelector("[data-new-doc]");
      if (button) button.addEventListener("click", openNewDocument);
      return;
    }
    list.innerHTML = state.documents
      .map((doc) => {
        const active = state.current && state.current.id === doc.id;
        const meta = doc.updated_at ? window.fmtDate(doc.updated_at).slice(5) : "";
        return (
          '<button class="doc-item' + (active ? " active" : "") + '" type="button" ' +
          'data-doc-id="' + doc.id + '"' + (active ? ' aria-current="true"' : "") + ">" +
          '<span class="doc-item-title">' + esc(doc.title) + "</span>" +
          '<span class="doc-item-meta">' + esc((doc.word_count || 0) + " 字") +
          (meta ? " · " + esc(meta) : "") + "</span></button>"
        );
      })
      .join("");
    list.querySelectorAll("[data-doc-id]").forEach((button) => {
      button.addEventListener("click", () => loadDocument(Number(button.dataset.docId)));
    });
  }

  async function loadDocuments() {
    try {
      const documents = await api.get("/api/projects/" + projectId + "/documents");
      state.documents = Array.isArray(documents) ? documents : [];
      W.setCounts({ documents: state.documents.length });
      renderDocuments();
      if (!state.current && state.documents.length) await loadDocument(state.documents[0].id);
    } catch (error) {
      W.showError($("#document-list"), error, { retry: loadDocuments });
    }
  }

  async function loadDocument(id) {
    if (state.current && state.current.id !== id) {
      if (state.conflict) {
        const ok = window.confirm("当前文档有保存冲突未处理，切换会丢失本地修改。仍要切换吗？");
        if (!ok) return;
      } else if (state.dirty && !state.saving) {
        await saveNow({ silent: true });
      }
    }
    try {
      const doc = await api.get("/api/documents/" + id);
      applyDocument(doc);
      await loadSnapshots();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function applyDocument(doc) {
    state.current = doc;
    state.dirty = false;
    state.conflict = false;
    const editor = $("#editor");
    const title = $("#document-title");
    if (editor) editor.value = doc.content_md || "";
    if (title) title.value = doc.title || "";
    hideConflict();
    updateWordCount();
    setSaveState("saved", "已保存 " + (doc.updated_at ? window.fmtDate(doc.updated_at).slice(11, 16) : ""));
    renderDocuments();
    renderParagraphCards();
  }

  function updateDocumentInList(doc) {
    const index = state.documents.findIndex((item) => item.id === doc.id);
    if (index >= 0) state.documents[index] = doc;
    renderDocuments();
  }

  async function saveNow(options = {}) {
    const current = state.current;
    const editor = $("#editor");
    if (!current || !editor || state.saving) return false;
    if (state.conflict) {
      if (!options.silent) toast("先处理版本冲突，再保存。", "error");
      return false;
    }
    if (!state.dirty) {
      if (!options.silent) toast("没有需要保存的修改。", "ok");
      return true;
    }
    clearTimeout(writing.timer);
    state.saving = true;
    setSaveState("saving", "保存中…");
    try {
      const saved = await api.put("/api/documents/" + current.id, {
        content_md: editor.value,
        version: current.version,
      });
      state.current = saved;
      state.dirty = editor.value !== saved.content_md;
      updateDocumentInList(saved);
      updateWordCount();
      if (state.dirty) {
        setSaveState("dirty", "有未保存修改");
        scheduleSave();
      } else {
        setSaveState("saved", "已保存 " + window.fmtDate(saved.updated_at).slice(11, 16));
        if (!options.silent) toast("已保存。", "ok");
      }
      return true;
    } catch (error) {
      if (error.status === 409) {
        state.conflict = true;
        setSaveState("conflict", "保存冲突");
        showConflict(error);
        toast("文档已被其他窗口修改，请刷新后再保存。", "error");
      } else {
        setSaveState("dirty", "保存失败");
        toast(error.message, "error");
      }
      return false;
    } finally {
      state.saving = false;
    }
  }

  function scheduleSave() {
    clearTimeout(writing.timer);
    writing.timer = setTimeout(() => {
      saveNow({ silent: true });
    }, 1500);
  }

  function showConflict(error) {
    const banner = $("#conflict-banner");
    const message = $("#conflict-message");
    if (message) message.textContent = (error && error.message) || "文档已被其他窗口修改，请刷新后再保存。";
    if (banner) banner.classList.remove("hidden");
  }

  function hideConflict() {
    const banner = $("#conflict-banner");
    if (banner) banner.classList.add("hidden");
  }

  async function reloadConflict() {
    if (!state.current) return;
    try {
      const doc = await api.get("/api/documents/" + state.current.id);
      applyDocument(doc);
      toast("已载入服务器最新版本。", "ok");
      await loadSnapshots();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function forceSave() {
    if (!state.current) return;
    const editor = $("#editor");
    if (!editor) return;
    const ok = window.confirm("用本地内容覆盖服务器最新版本？这不会保留其他窗口的修改。");
    if (!ok) return;
    try {
      const latest = await api.get("/api/documents/" + state.current.id);
      const saved = await api.put("/api/documents/" + state.current.id, {
        content_md: editor.value,
        version: latest.version,
      });
      state.current = saved;
      state.dirty = false;
      state.conflict = false;
      hideConflict();
      updateDocumentInList(saved);
      setSaveState("saved", "已保存 " + window.fmtDate(saved.updated_at).slice(11, 16));
      toast("已用本地内容保存。", "ok");
    } catch (error) {
      if (error.status === 409) {
        showConflict(error);
        toast("又发生冲突：请先载入最新版本。", "error");
      } else {
        toast(error.message, "error");
      }
    }
  }

  async function snapshotDocument(reason) {
    if (!state.current) return false;
    try {
      await api.post("/api/documents/" + state.current.id + "/snapshots", {
        reason: reason || "手动快照",
      });
      if (reason !== "接受改写" && reason !== "接受润色" && reason !== "接受调段") {
        toast("快照已保存。", "ok");
      }
      await loadSnapshots();
      return true;
    } catch (error) {
      toast(error.message, "error");
      return false;
    }
  }

  async function loadSnapshots() {
    const box = $("#snapshot-list");
    if (!box || !state.current) return;
    try {
      const snapshots = await api.get("/api/documents/" + state.current.id + "/snapshots");
      if (!Array.isArray(snapshots) || !snapshots.length) {
        box.innerHTML = '<p class="muted">还没有快照。</p>';
        return;
      }
      box.innerHTML = snapshots
        .map(
          (snap) =>
            '<div class="snapshot-item"><span>' +
            esc(window.fmtDate(snap.created_at)) +
            " · " +
            esc(snap.reason || "快照") +
            " · " +
            esc((snap.chars || 0) + " 字") +
            '</span><button class="btn ghost" type="button" data-restore="' + snap.id + '">恢复</button></div>'
        )
        .join("");
      box.querySelectorAll("[data-restore]").forEach((button) => {
        button.addEventListener("click", () => restoreSnapshot(Number(button.dataset.restore)));
      });
    } catch (error) {
      box.innerHTML = '<p class="muted">快照读取失败：' + esc(error.message) + "</p>";
    }
  }

  async function restoreSnapshot(snapshotId) {
    if (!state.current) return;
    const ok = window.confirm("恢复到这条快照？当前正文会被替换（旧正文仍可从最新快照找回）。");
    if (!ok) return;
    try {
      const doc = await api.post(
        "/api/documents/" + state.current.id + "/restore/" + snapshotId,
        {}
      );
      applyDocument(doc);
      updateDocumentInList(doc);
      toast("已恢复快照。", "ok");
      await loadSnapshots();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function openNewDocument() {
    const dialog = document.getElementById("new-document-dialog");
    const input = dialog && dialog.querySelector('input[name="title"]');
    if (!dialog) return;
    if (input) {
      input.value = "未命名文档";
      input.focus();
      input.select();
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  function paragraphsOf(text) {
    const chunks = [];
    if (!text) return chunks;
    const pattern = /\n\s*\n/g;
    let start = 0;
    let match;
    while ((match = pattern.exec(text))) {
      chunks.push({ start, end: match.index });
      start = pattern.lastIndex;
    }
    chunks.push({ start, end: text.length });
    return chunks
      .map((chunk) => {
        const raw = text.slice(chunk.start, chunk.end);
        const left = raw.length - raw.trimStart().length;
        const right = raw.length - raw.trimEnd().length;
        return {
          text: raw.trim(),
          start: chunk.start + left,
          end: chunk.end - right,
        };
      })
      .filter((chunk) => chunk.text.length > 0);
  }

  function renderParagraphCards() {
    const box = $("#paragraph-cards");
    const editor = $("#editor");
    const details = $("#paragraph-box");
    if (!box || !editor) return;
    if (details && !details.open) return;
    const paragraphs = paragraphsOf(editor.value || "");
    if (!paragraphs.length) {
      box.innerHTML = '<p class="muted">正文还是空的。</p>';
      return;
    }
    box.innerHTML = paragraphs
      .map(
        (paragraph, index) =>
          '<div class="para-card" data-para-index="' + index + '">' +
          '<span class="para-index">' + (index + 1) + "</span>" +
          '<p class="para-text">' + esc(paragraph.text) + "</p>" +
          '<div class="para-actions">' +
          '<button class="btn mini ghost" type="button" data-para-send="style">体检</button>' +
          '<button class="btn mini ghost" type="button" data-para-send="polish">润色</button>' +
          '<button class="btn mini ghost" type="button" data-para-send="paragraphs">调段</button>' +
          "</div></div>"
      )
      .join("");
    box.querySelectorAll("[data-para-send]").forEach((button) => {
      button.addEventListener("click", () => {
        const card = button.closest("[data-para-index]");
        const paragraphsNow = paragraphsOf($("#editor").value || "");
        const paragraph = paragraphsNow[Number(card.dataset.paraIndex)];
        if (!paragraph) {
          toast("段落已变化，请重试。", "error");
          return;
        }
        const target = {
          documentId: state.current ? state.current.id : null,
          start: paragraph.start,
          end: paragraph.end,
          original: paragraph.text,
        };
        W.sendText(button.dataset.paraSend, paragraph.text, target);
      });
    });
  }

  function currentTarget() {
    const editor = $("#editor");
    if (!editor || !state.current) return null;
    const value = editor.value || "";
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    if (typeof start === "number" && end > start) {
      const text = value.slice(start, end);
      if (text.trim()) {
        return { text, start, end, documentId: state.current.id };
      }
    }
    const caret = typeof start === "number" ? start : 0;
    const paragraphs = paragraphsOf(value);
    const found =
      paragraphs.find((paragraph) => caret >= paragraph.start && caret <= paragraph.end) ||
      paragraphs.find((paragraph, index) => index === paragraphs.length - 1);
    if (!found) return null;
    return {
      text: found.text,
      start: found.start,
      end: found.end,
      documentId: state.current.id,
    };
  }
  W.currentTarget = currentTarget;

  function bindWriting(panel) {
    if (writing.bound) return;
    writing.bound = true;
    const editor = panel.querySelector("#editor");
    if (!editor) return;
    const editorInput = () => {
      updateWordCount();
      state.dirty = true;
      clearTimeout(writing.paragraphTimer);
      writing.paragraphTimer = setTimeout(renderParagraphCards, 600);
      if (state.conflict) {
        setSaveState("conflict", "保存冲突");
      } else {
        setSaveState("dirty", "有未保存修改");
        scheduleSave();
      }
    };
    editor.addEventListener("input", editorInput);
    editor.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveNow();
      }
    });

    const saveButton = panel.querySelector("#save-document");
    if (saveButton) saveButton.addEventListener("click", () => saveNow());
    const snapshotButton = panel.querySelector("#snapshot-document");
    if (snapshotButton) snapshotButton.addEventListener("click", () => snapshotDocument("手动快照"));
    const newDocButton = panel.querySelector("#new-document");
    if (newDocButton) newDocButton.addEventListener("click", openNewDocument);

    const paragraphBox = panel.querySelector("#paragraph-box");
    if (paragraphBox) paragraphBox.addEventListener("toggle", renderParagraphCards);

    panel.querySelectorAll("[data-para-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = currentTarget();
        if (!target) {
          toast("写作页还没有打开文档。", "error");
          return;
        }
        W.sendText(button.dataset.paraAction, target.text, {
          documentId: target.documentId,
          start: target.start,
          end: target.end,
          original: target.text,
        });
      });
    });

    const reload = panel.querySelector("#conflict-reload");
    if (reload) reload.addEventListener("click", reloadConflict);
    const force = panel.querySelector("#conflict-force");
    if (force) force.addEventListener("click", forceSave);

    const form = document.getElementById("new-document-form");
    if (form) {
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        const title = String(data.get("title") || "").trim() || "未命名文档";
        try {
          const doc = await api.post("/api/projects/" + projectId + "/documents", {
            title,
            kind: String(data.get("kind") || "paper"),
          });
          state.documents.unshift(doc);
          W.setCounts({ documents: state.documents.length });
          const dialog = document.getElementById("new-document-dialog");
          if (dialog) dialog.close();
          await loadDocument(doc.id);
          toast("文档已创建。", "ok");
        } catch (error) {
          toast(error.message, "error");
        }
      });
    }

    loadDocuments();
  }

  W.views.writing = {
    mount(panel) {
      bindWriting(panel);
    },
    async show() {
      updateWordCount();
      if (!state.documents.length) await loadDocuments();
      await loadSnapshots();
    },
    setTarget() {
      /* writing is the source; nothing to fill here */
    },
  };

  W.saveNow = saveNow;
  W.snapshotDocument = snapshotDocument;
  W.updateWordCount = updateWordCount;
  W.editorText = () => {
    const editor = $("#editor");
    return editor ? editor.value : "";
  };

  /* ---------------- project settings ---------------- */

  const settingsButton = document.getElementById("workspace-settings");
  const projectDialog = document.getElementById("project-dialog");
  const projectForm = document.getElementById("project-form");
  if (settingsButton && projectDialog) {
    settingsButton.addEventListener("click", () => {
      if (typeof projectDialog.showModal === "function") projectDialog.showModal();
    });
  }
  if (projectForm) {
    projectForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(projectForm);
      const payload = {
        name: String(data.get("name") || "").trim(),
        field: String(data.get("field") || "").trim(),
        question: String(data.get("question") || "").trim(),
        description: String(data.get("description") || "").trim(),
      };
      if (!payload.name) {
        toast("项目名不能为空。", "error");
        return;
      }
      try {
        const project = await api.patch("/api/projects/" + projectId, payload);
        state.projectName = project.name;
        const heading = $(".workspace-head h1");
        if (heading) heading.textContent = project.name;
        const eyebrow = $(".workspace-head .eyebrow");
        if (eyebrow) eyebrow.textContent = project.field || "研究项目";
        const lede = $(".workspace-head .lede");
        if (lede) lede.textContent = project.question || "还没有写研究问题。";
        const stat = $("#stat-question");
        if (stat) stat.textContent = project.question ? "已写" : "待补";
        window.document.title = project.name + " · 文枢";
        if (projectDialog) projectDialog.close();
        toast("项目设置已保存。", "ok");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  }

  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = button.closest("dialog");
      if (dialog) dialog.close();
    });
  });

  /* ---------------- boot ---------------- */

  W.views.overview = {
    mount() {},
    async show() {
      if (!state.health) await refreshHealth();
    },
  };

  const initial = (location.hash || "").replace("#", "");
  refreshHealth();
  ensureMounted("writing").catch((error) => {
    console.error(error);
    toast("文档列表加载失败：" + error.message, "error");
  });
  openTab(panels[initial] ? initial : "overview");
})();
