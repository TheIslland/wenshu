/* 文献检索：源多选、筛选、结果卡、批量入库、按源显示错误。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  let panelEl = null;
  let bound = false;
  let hits = [];
  let selected = new Set();
  let lastQuery = "";

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;
    const form = $("#search-form");
    if (form) {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        runSearch();
      });
    }
    const all = $("#search-select-all");
    if (all) all.addEventListener("change", toggleAll);
    const importSelected = $("#import-all-hits");
    if (importSelected) importSelected.addEventListener("click", () => importHits(selectedHits()));
    const importEvery = $("#import-every-hit");
    if (importEvery) importEvery.addEventListener("click", () => importHits(hits));
    const results = $("#search-results");
    if (results) {
      results.addEventListener("change", onResultChange);
      results.addEventListener("click", onResultClick);
    }
  }

  function sources() {
    return Array.from(panelEl.querySelectorAll("#source-chips input:checked")).map(
      (input) => input.value
    );
  }

  function numberOrNull(selector) {
    const node = $(selector);
    if (!node || !node.value) return null;
    const value = Number(node.value);
    return Number.isFinite(value) ? value : null;
  }

  async function runSearch() {
    const queryNode = $("#search-query");
    const query = queryNode ? queryNode.value.trim() : "";
    if (!query) {
      toast("先输入检索词。", "error");
      return;
    }
    const chosen = sources();
    if (!chosen.length) {
      toast("至少勾选一个检索源。", "error");
      return;
    }
    lastQuery = query;
    selected = new Set();
    const results = $("#search-results");
    const actions = $("#search-actions");
    const errorsBox = $("#source-errors");
    W.loading(results, "正在检索 " + chosen.join(" / ") + "…");
    if (actions) actions.classList.add("hidden");
    if (errorsBox) errorsBox.innerHTML = "";
    try {
      const payload = {
        query,
        sources: chosen,
        limit: Number(($("#search-limit") || {}).value) || 20,
      };
      const yearFrom = numberOrNull("#search-year-from");
      const yearTo = numberOrNull("#search-year-to");
      const language = (($("#search-language") || {}).value || "").trim();
      if (yearFrom) payload.year_from = yearFrom;
      if (yearTo) payload.year_to = yearTo;
      if (language) payload.language = language;
      const data = await api.post("/api/search", payload);
      hits = Array.isArray(data && data.results) ? data.results : [];
      renderErrors(data && data.errors);
      renderResults(data, query);
      await syncRefCount();
    } catch (error) {
      hits = [];
      W.showError(results, error, { retry: runSearch });
      if (actions) actions.classList.add("hidden");
    }
  }

  function renderErrors(errors) {
    const box = $("#source-errors");
    if (!box) return;
    const entries = errors && typeof errors === "object" ? Object.entries(errors) : [];
    if (!entries.length) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = entries
      .map(
        ([source, message]) =>
          '<div class="source-error"><b>' + esc(source) + "</b>：" + esc(String(message)) + "</div>"
      )
      .join("");
    toast(
      "有 " + entries.length + " 个检索源失败，其他源结果已显示。",
      "error"
    );
  }

  function renderResults(data, query) {
    const results = $("#search-results");
    const actions = $("#search-actions");
    const summary = $("#search-summary");
    const total = Number((data && (data.total || (data && data.results && data.results.length))) || 0);
    const took = data && data.took_ms ? " · " + data.took_ms + " ms" : "";
    const cached = data && data.cached ? " · 本地缓存" : "";
    if (summary) {
      summary.textContent =
        "「" + query + "」去重后 " + hits.length + " 条" + (total && total !== hits.length ? "（源返回 " + total + "）" : "") + took + cached;
    }
    if (actions) actions.classList.remove("hidden");
    const all = $("#search-select-all");
    if (all) all.checked = false;
    updateImportButtons();
    if (!hits.length) {
      W.empty(
        results,
        "没有找到结果。",
        "换关键词、放宽年份，或去「文献」手动导入。注意：不生成检索结果之外的文献。",
        externalLinks(query)
      );
      return;
    }
    results.innerHTML =
      hits
        .map((hit, index) => {
          const title = esc(hit.title || "（无标题）");
          const authors = Array.isArray(hit.authors) ? hit.authors.join(", ") : hit.authors || "";
          const meta = [];
          meta.push('<span class="source-badge">' + esc(hit.source || "source") + "</span>");
          if (authors) meta.push("<span>" + esc(authors) + "</span>");
          if (hit.year) meta.push("<span>" + esc(hit.year) + "</span>");
          if (hit.venue) meta.push("<span>" + esc(hit.venue) + "</span>");
          if (hit.cited_by) meta.push("<span>被引 " + esc(hit.cited_by) + "</span>");
          if (hit.doi) meta.push('<span class="result-doi">DOI ' + esc(hit.doi) + "</span>");
          const links = [];
          if (hit.url) {
            links.push(
              '<a href="' + esc(hit.url) + '" target="_blank" rel="noopener noreferrer">原文</a>'
            );
          }
          if (hit.doi) {
            links.push(
              '<a href="https://doi.org/' + encodeURIComponent(hit.doi) +
                '" target="_blank" rel="noopener noreferrer">DOI</a>'
            );
          }
          return (
            '<article class="result-card" data-hit-index="' + index + '">' +
            '<div class="result-head">' +
            '<input class="result-check" type="checkbox" data-hit-check="' + index + '" aria-label="选择这条结果">' +
            '<div class="result-body">' +
            "<h3>" + title + "</h3>" +
            '<div class="result-meta">' + meta.join("") + "</div>" +
            '<p class="result-abstract">' + esc(hit.abstract || "（无摘要）") + "</p>" +
            '<div class="result-actions">' +
            '<button class="btn" type="button" data-hit-import="' + index + '">入库</button>' +
            links.join("") +
            "</div></div></div></article>"
          );
        })
        .join("") + externalLinks(query);
  }

  function externalLinks(query) {
    if (!query) return "";
    const q = encodeURIComponent(query);
    return (
      '<p class="hint external-hint">找不到时只提供跳转，不抓取：' +
      '<a href="https://scholar.google.com/scholar?q=' + q + '" target="_blank" rel="noopener noreferrer">Google Scholar</a> · ' +
      '<a href="https://www.cnki.net/" target="_blank" rel="noopener noreferrer">知网</a> · ' +
      '<a href="https://s.wanfangdata.com.cn/paper?q=' + q + '" target="_blank" rel="noopener noreferrer">万方</a>' +
      "</p>"
    );
  }

  function onResultChange(event) {
    const checkbox = event.target.closest("[data-hit-check]");
    if (!checkbox) return;
    const index = Number(checkbox.dataset.hitCheck);
    if (checkbox.checked) selected.add(index);
    else selected.delete(index);
    const card = checkbox.closest("[data-hit-index]");
    if (card) card.classList.toggle("selected", checkbox.checked);
    updateImportButtons();
  }

  function onResultClick(event) {
    const button = event.target.closest("[data-hit-import]");
    if (!button) return;
    const index = Number(button.dataset.hitImport);
    const hit = hits[index];
    if (hit) importHits([hit], button.closest("[data-hit-index]"));
  }

  function toggleAll(event) {
    const checked = event.target.checked;
    selected = new Set();
    panelEl.querySelectorAll("[data-hit-check]").forEach((checkbox) => {
      checkbox.checked = checked;
      const index = Number(checkbox.dataset.hitCheck);
      if (checked) selected.add(index);
      const card = checkbox.closest("[data-hit-index]");
      if (card) card.classList.toggle("selected", checked);
    });
    updateImportButtons();
  }

  function updateImportButtons() {
    const button = $("#import-all-hits");
    if (!button) return;
    button.disabled = selected.size === 0;
    button.textContent = selected.size ? "入库选中 (" + selected.size + ")" : "入库选中";
  }

  function selectedHits() {
    return Array.from(selected)
      .sort((a, b) => a - b)
      .map((index) => hits[index])
      .filter(Boolean);
  }

  async function importHits(items, card) {
    if (!items || !items.length) {
      toast("先勾选要入库的文献。", "error");
      return;
    }
    try {
      const result = await api.post("/api/refs/import", {
        project_id: W.projectId,
        kind: "hits",
        hits: items,
      });
      const imported = Number(result && result.imported) || 0;
      const skipped = Number(result && result.skipped) || 0;
      toast(
        "入库完成：新增 " + imported + " 条" + (skipped ? "，跳过重复 " + skipped + " 条" : "") + "。",
        "ok"
      );
      if (result && Array.isArray(result.warnings)) {
        result.warnings.slice(0, 3).forEach((warning) => toast(String(warning), "error"));
      }
      items.forEach((hit) => {
        const index = hits.indexOf(hit);
        const row = index >= 0 ? panelEl.querySelector('[data-hit-index="' + index + '"]') : null;
        if (row) {
          row.classList.add("added");
          const button = row.querySelector("[data-hit-import]");
          if (button) {
            button.disabled = true;
            button.textContent = "已入库";
          }
        }
      });
      if (card) card.classList.add("added");
      await syncRefCount();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function syncRefCount() {
    try {
      const data = await api.get("/api/refs?project_id=" + W.projectId);
      const list = Array.isArray(data) ? data : [];
      W.setCounts({ refs: list.length });
    } catch (_) {
      /* count is cosmetic; ignore */
    }
  }

  W.views.search = {
    mount,
    async show() {},
  };
})();
