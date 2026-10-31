/* 文献库：表格、筛选、导入（RIS/BibTeX/DOI）、PDF 上传、Zotero。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  const STATUS_LABELS = { inbox: "收件箱", reading: "在读", read: "已读", cited: "已引" };
  const STATUS_KEYS = ["inbox", "reading", "read", "cited"];

  let panelEl = null;
  let refs = [];
  let bound = false;
  let pendingPdfRef = null;

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;

    const search = $("#ref-search");
    if (search) search.addEventListener("input", window.debounce(loadRefs, 300));
    const status = $("#ref-status");
    if (status) status.addEventListener("change", loadRefs);

    const importButton = $("#import-refs");
    if (importButton) importButton.addEventListener("click", openImportDialog);
    const zotero = $("#zotero-import");
    if (zotero) zotero.addEventListener("click", importFromZotero);

    const table = $("#ref-table");
    if (table) {
      table.addEventListener("click", onTableClick);
      table.addEventListener("change", onTableChange);
    }

    const pdfInput = $("#pdf-input");
    if (pdfInput) pdfInput.addEventListener("change", uploadPdf);

    bindImportDialog();
    loadRefs();
  }

  function bindImportDialog() {
    const dialog = document.getElementById("import-dialog");
    const form = document.getElementById("import-form");
    const kind = document.getElementById("import-kind");
    if (!dialog || !form || !kind) return;
    kind.addEventListener("change", syncImportFields);
    syncImportFields();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitImport();
    });
  }

  function syncImportFields() {
    const kind = document.getElementById("import-kind");
    const payloadWrap = document.getElementById("import-payload-wrap");
    const doiWrap = document.getElementById("import-doi-wrap");
    const fileWrap = document.getElementById("import-file-wrap");
    if (!kind) return;
    const isDoi = kind.value === "doi";
    const isPdf = kind.value === "pdf";
    if (payloadWrap) payloadWrap.classList.toggle("hidden", isDoi || isPdf);
    if (doiWrap) doiWrap.classList.toggle("hidden", !isDoi);
    if (fileWrap) fileWrap.classList.toggle("hidden", !isPdf);
  }

  function openImportDialog() {
    const dialog = document.getElementById("import-dialog");
    if (!dialog) return;
    const kind = document.getElementById("import-kind");
    if (kind) {
      kind.value = "ris";
      syncImportFields();
    }
    if (typeof dialog.showModal === "function") dialog.showModal();
  }

  async function submitImport() {
    const kindNode = document.getElementById("import-kind");
    const submit = document.getElementById("import-submit");
    const kind = kindNode ? kindNode.value : "ris";
    if (submit) submit.disabled = true;
    try {
      if (kind === "pdf") {
        const fileInput = document.getElementById("import-file");
        const file = fileInput && fileInput.files && fileInput.files[0];
        if (!file) {
          toast("先选择一个 PDF 文件。", "error");
          return;
        }
        const form = new FormData();
        form.append("file", file, file.name);
        form.append("project_id", String(W.projectId));
        const result = await api.upload("/api/refs/import/file", form);
        const imported = Number(result && result.imported) || 0;
        toast(
          "PDF 导入完成：新增 " + imported + " 条" +
            (result && result.warnings && result.warnings.length ? "。" + result.warnings[0] : "。"),
          "ok"
        );
        const dialog = document.getElementById("import-dialog");
        if (dialog) dialog.close();
        fileInput.value = "";
        await loadRefs();
        return;
      }
      const payload =
        kind === "doi"
          ? (document.getElementById("import-doi") || {}).value
          : (document.getElementById("import-payload") || {}).value;
      const text = String(payload || "").trim();
      if (!text) {
        toast(kind === "doi" ? "先填一个 DOI。" : "先粘贴 RIS / BibTeX 内容。", "error");
        return;
      }
      const result = await api.post("/api/refs/import", {
        project_id: W.projectId,
        kind,
        payload: text,
      });
      const imported = Number(result && result.imported) || 0;
      const skipped = Number(result && result.skipped) || 0;
      toast(
        "导入完成：新增 " + imported + " 条" + (skipped ? "，跳过重复 " + skipped + " 条" : "") + "。",
        "ok"
      );
      if (result && Array.isArray(result.warnings)) {
        result.warnings.slice(0, 3).forEach((warning) => toast(String(warning), "error"));
      }
      const dialog = document.getElementById("import-dialog");
      if (dialog) dialog.close();
      const payloadNode = document.getElementById("import-payload");
      if (payloadNode) payloadNode.value = "";
      const doiNode = document.getElementById("import-doi");
      if (doiNode) doiNode.value = "";
      await loadRefs();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function importFromZotero() {
    const button = $("#zotero-import");
    if (button) button.disabled = true;
    try {
      const status = await api.get("/api/zotero/status");
      if (!status || !status.running) {
        toast(
          (status && status.message) || "Zotero 本地接口不可用：请打开 Zotero 7 并启用本地 API。",
          "error"
        );
        return;
      }
      const result = await api.post("/api/zotero/import", { project_id: W.projectId });
      const imported = Number(result && result.imported) || 0;
      toast("Zotero 导入完成：新增 " + imported + " 条。", "ok");
      await loadRefs();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function statusOptions(current) {
    const value = current || "inbox";
    return STATUS_KEYS.map(
      (key) =>
        '<option value="' + key + '"' + (key === value ? " selected" : "") + ">" +
        esc(STATUS_LABELS[key]) +
        "</option>"
    ).join("");
  }

  function render() {
    const table = $("#ref-table");
    const summary = $("#ref-summary");
    if (summary) summary.textContent = refs.length ? "共 " + refs.length + " 条" : "空";
    if (!table) return;
    if (!refs.length) {
      W.empty(
        table,
        "文献库还是空的。",
        "去「检索」找，或导入 RIS / BibTeX / DOI / Zotero。",
        '<button class="btn" type="button" data-empty-action="import">导入文献</button>' +
          '<button class="btn ghost" type="button" data-empty-action="search">去检索</button>'
      );
      table.querySelectorAll("[data-empty-action]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.dataset.emptyAction === "import") openImportDialog();
          else if (W.openTab) W.openTab("search");
        });
      });
      return;
    }
    const rows = refs
      .map((ref) => {
        const authors = Array.isArray(ref.authors) ? ref.authors.join(", ") : ref.authors || "";
        const subParts = [];
        if (ref.bibkey) subParts.push(ref.bibkey);
        if (ref.doi) subParts.push(ref.doi);
        else if (ref.source) subParts.push(ref.source);
        const title = esc(ref.title || "（无标题）");
        const link = ref.url
          ? '<a href="' + esc(ref.url) + '" target="_blank" rel="noopener noreferrer">打开</a>'
          : "";
        const pdf = ref.has_fulltext
          ? '<button class="btn ghost" type="button" data-ref-action="attach" data-ref-id="' + ref.id + '">换 PDF</button>'
          : '<button class="btn ghost" type="button" data-ref-action="attach" data-ref-id="' + ref.id + '">上传 PDF</button>';
        return (
          "<tr data-row-ref=\"" + ref.id + '">' +
          '<td><div class="ref-title">' + title + "</div>" +
          (subParts.length ? '<div class="ref-sub">' + esc(subParts.join(" · ")) + "</div>" : "") +
          "</td>" +
          "<td>" + esc(authors) + "</td>" +
          '<td class="num">' + esc(ref.year || "") + "</td>" +
          "<td>" + esc(ref.venue || "") + "</td>" +
          '<td><select class="status-select" data-ref-status="' + ref.id + '">' +
          statusOptions(ref.status) + "</select></td>" +
          '<td class="ref-actions">' + pdf + link + "</td>" +
          "</tr>"
        );
      })
      .join("");
    table.innerHTML =
      '<table class="ref-table"><thead><tr>' +
      "<th>标题</th><th>作者</th><th>年份</th><th>期刊 / 出版社</th><th>状态</th><th>操作</th>" +
      "</tr></thead><tbody>" + rows + "</tbody></table>";
  }

  async function loadRefs() {
    const table = $("#ref-table");
    const search = $("#ref-search");
    const status = $("#ref-status");
    if (!table) return;
    W.loading(table, "正在加载文献库…");
    try {
      const params = new URLSearchParams();
      params.set("project_id", String(W.projectId));
      const q = search ? search.value.trim() : "";
      const filter = status ? status.value : "";
      if (q) params.set("q", q);
      if (filter) params.set("status", filter);
      const data = await api.get("/api/refs?" + params.toString());
      refs = Array.isArray(data) ? data : Array.isArray(data && data.refs) ? data.refs : [];
      render();
      W.setCounts({ refs: refs.length });
    } catch (error) {
      W.showError(table, error, { retry: loadRefs });
      const summary = $("#ref-summary");
      if (summary) summary.textContent = "加载失败";
    }
  }

  function onTableClick(event) {
    const target = event.target.closest("[data-ref-action]");
    if (!target || !panelEl.contains(target)) return;
    if (target.dataset.refAction === "attach") {
      pendingPdfRef = Number(target.dataset.refId);
      const input = $("#pdf-input");
      if (!input) return;
      input.value = "";
      input.click();
    }
  }

  function onTableChange(event) {
    const select = event.target.closest("[data-ref-status]");
    if (!select) return;
    const id = Number(select.dataset.refStatus);
    const next = select.value;
    const ref = refs.find((item) => item.id === id);
    const previous = ref ? ref.status : "";
    if (ref) ref.status = next;
    api
      .patch("/api/refs/" + id, { status: next })
      .then((updated) => {
        if (updated && updated.id && ref) Object.assign(ref, updated);
        toast("状态已更新为「" + (STATUS_LABELS[next] || next) + "」。", "ok");
      })
      .catch((error) => {
        select.value = previous || "inbox";
        toast(error.message, "error");
      });
  }

  async function uploadPdf(event) {
    const input = event.target;
    const file = input.files && input.files[0];
    const refId = pendingPdfRef;
    if (!file || !refId) return;
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") {
      toast("只支持 PDF 文件。", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file, file.name);
    const summary = $("#ref-summary");
    if (summary) summary.textContent = "正在上传 PDF 并抽取全文…";
    try {
      const updated = await api.upload("/api/refs/" + refId + "/attach", form);
      const index = refs.findIndex((item) => item.id === refId);
      if (index >= 0 && updated && updated.id) refs[index] = updated;
      render();
      toast(
        "PDF 已保存" +
          (updated && updated.has_fulltext ? "，全文已入库（可被全文检索）。" : "，但未抽出可用文本。"),
        "ok"
      );
    } catch (error) {
      toast(error.message, "error");
      if (summary) summary.textContent = "共 " + refs.length + " 条";
    } finally {
      pendingPdfRef = null;
      input.value = "";
    }
  }

  W.views.library = {
    mount,
    async show() {
      await loadRefs();
    },
  };
})();
