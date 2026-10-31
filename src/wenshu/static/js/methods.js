/* 方法矩阵：可编辑表格 + 年份 SVG 柱状图 + 冲突提示。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  const FIELDS = [
    ["method", "方法"],
    ["data", "数据来源"],
    ["sample", "样本"],
    ["theory", "理论视角"],
    ["finding", "核心结论"],
    ["limitation", "局限"],
  ];

  let panelEl = null;
  let bound = false;
  let matrix = { rows: [], trend: [], method_trend: [], conflicts: [] };
  let busy = false;

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;
    const extract = $("#extract-methods");
    if (extract) extract.addEventListener("click", extractMethods);
    const refresh = $("#refresh-methods");
    if (refresh) refresh.addEventListener("click", loadMatrix);
    const exportButton = $("#export-methods");
    if (exportButton) exportButton.addEventListener("click", exportCsv);
    const matrixNode = $("#method-matrix");
    if (matrixNode) matrixNode.addEventListener("click", onCellClick);
    const trend = $("#method-trend");
    if (trend) trend.addEventListener("click", () => {});
    loadMatrix();
  }

  async function loadMatrix() {
    const node = $("#method-matrix");
    if (!node) return;
    W.loading(node, "正在加载方法矩阵…");
    try {
      const data = await api.get("/api/methods/matrix?project_id=" + W.projectId);
      matrix = {
        rows: Array.isArray(data && data.rows) ? data.rows : [],
        trend: Array.isArray(data && data.trend) ? data.trend : [],
        method_trend: Array.isArray(data && data.method_trend) ? data.method_trend : [],
        conflicts: Array.isArray(data && data.conflicts) ? data.conflicts : [],
        openalex_trend: Array.isArray(data && data.openalex_trend) ? data.openalex_trend : [],
        warnings: Array.isArray(data && data.warnings) ? data.warnings : [],
      };
      render();
    } catch (error) {
      W.showError(node, error, { retry: loadMatrix });
      const summary = $("#method-summary");
      if (summary) summary.textContent = "加载失败";
    }
  }

  async function extractMethods() {
    const button = $("#extract-methods");
    if (busy) return;
    busy = true;
    if (button) button.disabled = true;
    const node = $("#method-matrix");
    W.loading(node, "正在从摘要与笔记抽取方法…");
    try {
      const result = await api.post("/api/methods/extract", { project_id: W.projectId });
      const extracted = Number(result && result.extracted) || 0;
      const skipped = Number(result && result.skipped) || 0;
      toast(
        "抽取完成：新增 " + extracted + " 条" + (skipped ? "，跳过 " + skipped + " 条" : "") + "。",
        "ok"
      );
      if (result && Array.isArray(result.warnings)) {
        result.warnings.slice(0, 3).forEach((warning) => toast(String(warning), "error"));
      }
      await loadMatrix();
    } catch (error) {
      W.showError(node, error, { retry: extractMethods });
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  function render() {
    renderSummary();
    renderConflicts();
    renderTable();
    renderTrend();
  }

  function renderSummary() {
    const summary = $("#method-summary");
    if (!summary) return;
    const years = matrix.trend
      .map((point) => Number(point && point.year))
      .filter((year) => Number.isFinite(year) && year > 0);
    const range = years.length
      ? " · 年份 " + Math.min(...years) + "–" + Math.max(...years)
      : "";
    summary.textContent = matrix.rows.length + " 条方法行" + range;
  }

  function renderConflicts() {
    const box = $("#method-conflicts");
    if (!box) return;
    const conflicts = matrix.conflicts || [];
    if (!conflicts.length) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = conflicts
      .map((conflict) => {
        const who = [conflict.author, conflict.sample].filter(Boolean).join(" · ");
        const message =
          conflict.message ||
          (Array.isArray(conflict.findings) ? conflict.findings.join("；") : "") ||
          "同一作者 / 样本的结论存在冲突，导出前请核对。";
        return (
          '<div class="conflict-item">' +
          (who ? "<b>" + esc(who) + "</b>：" : "") +
          esc(String(message)) +
          "</div>"
        );
      })
      .join("");
  }

  function refLabel(row) {
    const title = row.ref_title || (row.ref_id ? "文献 #" + row.ref_id : "（未关联文献）");
    const meta = [row.ref_authors, row.ref_year, row.ref_venue]
      .filter((part) => part && (!Array.isArray(part) || part.length))
      .map((part) => (Array.isArray(part) ? part.join(", ") : String(part)));
    return (
      '<div class="matrix-ref">' + esc(title) + "</div>" +
      (meta.length ? '<div class="matrix-evidence">' + esc(meta.join(" · ")) + "</div>" : "")
    );
  }

  function evidenceHtml(row) {
    const evidence = Array.isArray(row.evidence) ? row.evidence.filter(Boolean) : [];
    if (!evidence.length) return '<span class="empty-cell">无证据句</span>';
    const first = String(evidence[0]);
    return (
      '<div class="matrix-evidence" title="' + esc(evidence.join("\n")) + '">' +
      esc(first.length > 80 ? first.slice(0, 80) + "…" : first) +
      (evidence.length > 1 ? "（" + evidence.length + " 条）" : "") +
      "</div>"
    );
  }

  function renderTable() {
    const node = $("#method-matrix");
    if (!node) return;
    if (!matrix.rows.length) {
      W.empty(
        node,
        "矩阵还是空的。",
        "先在文献库入库，再点「从文献抽取方法」；规则词典离线可跑，LLM 只做补充。",
        '<button class="btn" type="button" data-method-action="extract">从文献抽取方法</button>' +
          '<button class="btn ghost" type="button" data-method-action="library">去文献库</button>'
      );
      node.querySelectorAll("[data-method-action]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.dataset.methodAction === "extract") extractMethods();
          else if (W.openTab) W.openTab("library");
        });
      });
      return;
    }
    const head =
      "<tr><th>文献</th><th>年份</th>" +
      FIELDS.map(([, label]) => "<th>" + label + "</th>").join("") +
      "<th>证据</th></tr>";
    const body = matrix.rows
      .map((row) => {
        const id = row.id;
        const cells = FIELDS.map(([field, label]) => {
          const value = row[field] == null ? "" : String(row[field]);
          const empty = !value.trim();
          return (
            '<td class="cell-edit" data-row-id="' + esc(id) + '" data-field="' + field +
            '" tabindex="0" role="button" aria-label="编辑' + label + '">' +
            (empty
              ? '<span class="empty-cell">未抽取</span>'
              : esc(value)) +
            "</td>"
          );
        }).join("");
        return (
          "<tr>" +
          "<td>" + refLabel(row) + "</td>" +
          '<td class="num">' + esc(row.ref_year || "") + "</td>" +
          cells +
          "<td>" + evidenceHtml(row) + "</td>" +
          "</tr>"
        );
      })
      .join("");
    node.innerHTML =
      '<table class="matrix-table"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  }

  function renderTrend() {
    const box = $("#method-trend");
    if (!box) return;
    const points = (matrix.trend || [])
      .map((point) => ({ year: Number(point && point.year), count: Number(point && point.count) || 0 }))
      .filter((point) => Number.isFinite(point.year) && point.year > 0)
      .sort((a, b) => a.year - b.year);
    const fallback = (matrix.openalex_trend || [])
      .map((point) => ({ year: Number(point && point.year), count: Number(point && point.count) || 0 }))
      .filter((point) => Number.isFinite(point.year) && point.year > 0)
      .sort((a, b) => a.year - b.year);
    const data = points.length ? points : fallback;
    if (!data.length) {
      box.innerHTML = '<p class="trend-caption">还没有年份数据。入库带年份的文献后，这里会出现本地库年份分布。</p>';
      return;
    }
    const caption = points.length ? "本地库年份分布" : "OpenAlex 年度产量（离线时可能为空）";
    const svg = barChart(data);
    const methodCounts = aggregateMethods(matrix.method_trend);
    box.innerHTML =
      "<h3>" + esc(caption) + "</h3>" +
      svg +
      '<p class="trend-caption">年份分布只统计本地库；不改文献元数据。</p>' +
      (methodCounts.length ? methodBars(methodCounts) : "");
  }

  function barChart(data) {
    const width = 680;
    const height = 210;
    const pad = { left: 38, right: 14, top: 18, bottom: 30 };
    const innerWidth = width - pad.left - pad.right;
    const innerHeight = height - pad.top - pad.bottom;
    const max = Math.max.apply(
      null,
      data.map((point) => point.count).concat([1])
    );
    const step = innerWidth / Math.max(data.length, 1);
    const barWidth = Math.max(4, Math.min(34, step * 0.62));
    const skip = Math.max(1, Math.ceil(data.length / 14));
    const bars = data
      .map((point, index) => {
        const barHeight = (point.count / max) * innerHeight;
        const x = pad.left + step * index + (step - barWidth) / 2;
        const y = pad.top + innerHeight - barHeight;
        return (
          '<rect class="bar" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
          '" width="' + barWidth.toFixed(1) + '" height="' + barHeight.toFixed(1) +
          '" rx="2"><title>' + esc(point.year) + " 年：" + esc(point.count) + " 篇</title></rect>" +
          '<text class="bar-value" x="' + (x + barWidth / 2).toFixed(1) + '" y="' +
          (y - 4).toFixed(1) + '" text-anchor="middle">' + esc(point.count) + "</text>" +
          (index % skip === 0
            ? '<text class="bar-label" x="' + (x + barWidth / 2).toFixed(1) + '" y="' +
              (height - 10) + '" text-anchor="middle">' + esc(point.year) + "</text>"
            : "")
        );
      })
      .join("");
    return (
      '<svg class="trend-svg" viewBox="0 0 ' + width + " " + height +
      '" role="img" aria-label="年份分布柱状图">' +
      '<line class="axis" x1="' + pad.left + '" y1="' + (pad.top + innerHeight) +
      '" x2="' + (width - pad.right) + '" y2="' + (pad.top + innerHeight) + '"></line>' +
      bars + "</svg>"
    );
  }

  function aggregateMethods(methodTrend) {
    if (!Array.isArray(methodTrend)) return [];
    const counts = new Map();
    methodTrend.forEach((point) => {
      const method = point && (point.method || point.name);
      if (!method) return;
      counts.set(method, (counts.get(method) || 0) + (Number(point.count) || 0));
    });
    return Array.from(counts.entries())
      .map(([method, count]) => ({ method, count }))
      .filter((item) => item.count > 0)
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }

  function methodBars(items) {
    const max = Math.max.apply(null, items.map((item) => item.count).concat([1]));
    return (
      '<h3 class="chart-sub">方法词频</h3><div class="method-bars">' +
      items
        .map((item) => {
          const width = Math.round((item.count / max) * 100);
          return (
            '<div class="bar"><span>' + esc(item.method) + '</span><i style="width:' + width + '%"></i>' +
            "<em>" + esc(item.count) + "</em></div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function onCellClick(event) {
    const cell = event.target.closest("td.cell-edit");
    if (!cell || !panelEl.contains(cell)) return;
    if (cell.querySelector("textarea")) return;
    editCell(cell);
  }

  function editCell(cell) {
    const rowId = cell.dataset.rowId;
    const field = cell.dataset.field;
    if (!rowId || !field) return;
    const row = matrix.rows.find((item) => String(item.id) === String(rowId));
    if (!row) return;
    const original = row[field] == null ? "" : String(row[field]);
    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.value = original;
    cell.classList.remove("saved", "error");
    cell.innerHTML = "";
    cell.appendChild(textarea);
    textarea.focus();
    textarea.addEventListener("keydown", (keyEvent) => {
      if (keyEvent.key === "Escape") {
        keyEvent.preventDefault();
        cell.textContent = original;
        renderCellPlaceholder(cell, original);
      } else if ((keyEvent.ctrlKey || keyEvent.metaKey) && keyEvent.key === "Enter") {
        textarea.blur();
      }
    });
    textarea.addEventListener("blur", async () => {
      const next = textarea.value.trim();
      if (next === original.trim()) {
        renderCell(cell, next);
        return;
      }
      cell.classList.add("saving");
      try {
        const payload = {};
        payload[field] = next;
        const updated = await api.patch("/api/methods/rows/" + rowId, payload);
        row[field] = next;
        if (updated && typeof updated === "object" && updated.id) Object.assign(row, updated);
        renderCell(cell, row[field] == null ? "" : String(row[field]));
        cell.classList.remove("saving");
        cell.classList.add("saved");
        setTimeout(() => cell.classList.remove("saved"), 1200);
      } catch (error) {
        cell.classList.remove("saving");
        cell.classList.add("error");
        renderCell(cell, original);
        setTimeout(() => cell.classList.remove("error"), 1800);
        toast(error.message, "error");
      }
    });
  }

  function renderCellPlaceholder(cell, value) {
    cell.textContent = "";
    if (!value || !value.trim()) {
      cell.innerHTML = '<span class="empty-cell">未抽取</span>';
    } else {
      cell.textContent = value;
    }
  }

  function renderCell(cell, value) {
    renderCellPlaceholder(cell, value);
  }

  function exportCsv() {
    if (!matrix.rows.length) {
      toast("矩阵是空的，先抽取方法。", "error");
      return;
    }
    const header = ["ref_id", "ref_title", "ref_year"].concat(FIELDS.map(([field]) => field));
    const lines = [header.join(",")];
    matrix.rows.forEach((row) => {
      const values = [row.ref_id || "", row.ref_title || "", row.ref_year || ""].concat(
        FIELDS.map(([field]) => row[field] || "")
      );
      lines.push(
        values
          .map((value) => {
            const text = String(value == null ? "" : value).replaceAll('"', '""');
            return '"' + text + '"';
          })
          .join(",")
      );
    });
    const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "wenshu-methods-" + W.projectId + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast("矩阵 CSV 已下载。", "ok");
  }

  W.views.methods = {
    mount,
    async show() {
      if (!matrix.rows.length) await loadMatrix();
    },
  };
})();
