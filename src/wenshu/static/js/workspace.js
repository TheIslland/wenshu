/* Workspace shell: tabs + editor. Extended by the frontend workstream. */
(function () {
  const root = document.getElementById("workspace");
  if (!root) return;
  const projectId = Number(root.dataset.projectId);
  const state = { documents: [], current: null, timer: null };

  const $ = (selector) => root.querySelector(selector);
  const editor = $("#editor");
  const title = $("#document-title");
  const wordCount = $("#word-count");

  function activateTab(name) {
    root.querySelectorAll(".tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.tab === name);
    });
    root.querySelectorAll(".tab-panel").forEach((panel) => {
      panel.classList.toggle("active", panel.dataset.panel === name);
    });
    if (name === "library") loadRefs();
  }

  root.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => { activateTab(tab.dataset.tab); });
  });
  root.querySelectorAll("[data-goto]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.goto));
  });

  function setWordCount() {
    const text = editor.value || "";
    const cjk = (text.match(/[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]/g) || []).length;
    const latin = (text.match(/[A-Za-z0-9]+/g) || []).length;
    wordCount.textContent = `${cjk + latin} 字`;
  }

  function renderDocs() {
    const list = $("#document-list");
    list.innerHTML = "";
    state.documents.forEach((doc) => {
      const button = document.createElement("button");
      button.className = "doc-item" + (state.current && state.current.id === doc.id ? " active" : "");
      button.textContent = doc.title;
      button.addEventListener("click", () => loadDocument(doc.id));
      list.appendChild(button);
    });
  }

  async function loadDocuments() {
    state.documents = await api.get(`/api/projects/${projectId}/documents`);
    renderDocs();
    if (!state.current && state.documents.length) await loadDocument(state.documents[0].id);
  }

  async function loadDocument(id) {
    if (state.current && editor.value !== state.current.content_md) await saveNow();
    const doc = await api.get(`/api/documents/${id}`);
    state.current = doc;
    title.value = doc.title;
    editor.value = doc.content_md || "";
    setWordCount();
    renderDocs();
  }

  async function saveNow() {
    if (!state.current) return;
    try {
      const saved = await api.put(`/api/documents/${state.current.id}`, {
        content_md: editor.value,
        version: state.current.version,
      });
      state.current = saved;
      const index = state.documents.findIndex((doc) => doc.id === saved.id);
      if (index >= 0) state.documents[index] = saved;
      setWordCount();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  const autosave = debounce(saveNow, 1500);
  editor.addEventListener("input", () => {
    setWordCount();
    autosave();
  });

  const saveButton = $("#save-document");
  if (saveButton) saveButton.addEventListener("click", saveNow);

  const snapshot = $("#snapshot-document");
  if (snapshot) snapshot.addEventListener("click", async () => {
    if (!state.current) return;
    try {
      await api.post(`/api/documents/${state.current.id}/snapshots`, { reason: "手动快照" });
      toast("快照已保存。", "ok");
    } catch (error) { toast(error.message, "error"); }
  });

  const newDoc = $("#new-document");
  if (newDoc) newDoc.addEventListener("click", async () => {
    try {
      const doc = await api.post(`/api/projects/${projectId}/documents`, {
        title: "未命名文档", kind: "notes",
      });
      state.documents.unshift(doc);
      await loadDocument(doc.id);
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadRefs() {
    try {
      const refs = await api.get(`/api/refs?project_id=${projectId}`);
      const table = $("#ref-table");
      if (!refs.length) {
        table.innerHTML = '<div class="empty"><p>文献库还是空的。</p><p class="muted">去「检索」找，或导入 RIS / BibTeX / Zotero。</p></div>';
        return;
      }
      table.innerHTML = `<table><thead><tr><th>标题</th><th>作者</th><th>年份</th><th>状态</th></tr></thead><tbody>${
        refs.map((ref) => `<tr><td>${escapeHtml(ref.title)}</td><td>${escapeHtml((ref.authors || []).join(", "))}</td><td>${ref.year || ""}</td><td>${escapeHtml(ref.status || "")}</td></tr>`).join("")
      }</tbody></table>`;
    } catch (error) { toast(error.message, "error"); }
  }

  loadDocuments().catch((error) => toast(error.message, "error"));
})();
