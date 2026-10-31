/* 交付：导出、门禁、引用格式预览、批量核引。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  const STATUS_LABELS = {
    verified: "已核",
    mismatch: "不匹配",
    not_found: "未找到",
    no_doi: "无 DOI",
    error: "出错",
  };
  const STATUS_CLASSES = {
    verified: "ok",
    mismatch: "danger",
    not_found: "warn",
    no_doi: "muted",
    error: "danger",
  };
  const STATUS_ORDER = ["verified", "mismatch", "not_found", "no_doi", "error"];

  const EXPORTS = [
    { selector: "#export-markdown", fmt: "markdown", label: "Markdown", ext: "md" },
    { selector: "#export-docx", fmt: "docx", label: "DOCX", ext: "docx" },
    { selector: "#export-bibtex", fmt: "bibtex", label: "BibTeX", ext: "bib" },
    { selector: "#export-ris", fmt: "ris", label: "RIS", ext: "ris" },
  ];

  let panelEl = null;
  let bound = false;
  let gateData = null;
  let busy = false;

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;

    EXPORTS.forEach((item) => {
      const button = $(item.selector);
      if (button) button.addEventListener("click", () => exportFile(item));
    });
    const gateRefresh = $("#delivery-gate-refresh");
    if (gateRefresh) gateRefresh.addEventListener("click", loadGate);
    const preview = $("#citation-preview");
    if (preview) preview.addEventListener("click", renderCitationPreview);
    const style = $("#citation-style");
    if (style) style.addEventListener("change", renderCitationPreview);
    const verify = $("#citation-verify");
    if (verify) verify.addEventListener("click", verifyCitations);
    const refreshChecks = $("#citation-refresh-checks");
    if (refreshChecks) refreshChecks.addEventListener("click", loadChecks);
  }

  async function loadGate() {
    const box = $("#delivery-gate");
    if (!box) return;
    W.loading(box, "正在检查门禁…");
    try {
      gateData = await api.get("/api/workflow/gate?project_id=" + W.projectId);
      renderGate(gateData);
    } catch (error) {
      gateData = null;
      W.showError(box, error, { retry: loadGate });
    }
  }

  function renderGate(data) {
    const box = $("#delivery-gate");
    if (!box) return;
    const blockers = Array.isArray(data && data.blockers) ? data.blockers : [];
    if (!blockers.length) {
      box.innerHTML =
        '<div class="gate-ok"><strong>门禁通过。</strong>未核引、高风险段与未解决 gaps 都没有阻塞项。</div>';
      return;
    }
    box.innerHTML =
      '<div class="banner danger"><div><strong>门禁：' + blockers.length + " 项未通过。</strong>" +
      esc("导出仍可继续，但请先确认这些风险：") +
      "</div></div>" +
      '<ul class="gate-list">' +
      groupBlockers(blockers)
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

  function groupBlockers(blockers) {
    const labels = { citation: "未核引", style: "高风险段未处理", gap: "未解决 gaps" };
    const groups = new Map();
    blockers.forEach((blocker) => {
      const label = labels[blocker && blocker.type] || (blocker && blocker.type) || "问题";
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

  function filenameFor(item) {
    const name = String(W.projectName || "wenshu-project")
      .replace(/[\\/:*?"<>|]+/g, "-")
      .replace(/\s+/g, "-")
      .slice(0, 60);
    return "wenshu-" + (name || "project") + "." + item.ext;
  }

  async function exportFile(item) {
    if (busy) return;
    const blockers = gateData && Array.isArray(gateData.blockers) ? gateData.blockers : [];
    if (blockers.length) {
      const ok = window.confirm(
        "门禁还有 " + blockers.length + " 项未通过（未核引 / 高风险段 / gaps）。仍然导出 " +
          item.label + " 吗？"
      );
      if (!ok) return;
    }
    const styleNode = $("#export-style");
    const style = styleNode ? styleNode.value : "gbt7714";
    const status = $("#export-status");
    if (status) status.textContent = "正在导出 " + item.label + "…";
    busy = true;
    try {
      await api.download(
        "/api/export/" + item.fmt,
        { project_id: W.projectId, style },
        filenameFor(item)
      );
      if (status) status.textContent = "已导出 " + item.label + "（" + filenameFor(item) + "）。";
      toast(item.label + " 已开始下载。", "ok");
    } catch (error) {
      if (status) status.textContent = "导出失败：" + error.message;
      toast(error.message, "error");
    } finally {
      busy = false;
    }
  }

  async function renderCitationPreview() {
    const styleNode = $("#citation-style");
    const pre = $("#citation-text");
    const meta = $("#citation-meta");
    const warningsBox = $("#citation-warnings");
    if (!pre) return;
    const style = styleNode ? styleNode.value : "gbt7714";
    pre.textContent = "正在生成引用格式…";
    if (warningsBox) warningsBox.innerHTML = "";
    try {
      const data = await api.get(
        "/api/citations/format?project_id=" + W.projectId + "&style=" + encodeURIComponent(style)
      );
      const text = String((data && data.text) || "").trim();
      pre.textContent = text || "本地库还没有可用于格式化的文献。先去「文献」入库。";
      if (meta) {
        meta.textContent =
          String((data && data.count) || 0) +
          " 条 · " +
          (data && data.engine === "citeproc" ? "citeproc + CSL" : "内置格式化") +
          " · " +
          String((data && data.style) || style);
      }
      if (warningsBox && data && Array.isArray(data.warnings)) {
        warningsBox.innerHTML = W.warningsHtml(data.warnings);
      }
    } catch (error) {
      const info = W.describeError(error);
      pre.textContent = "预览失败：" + info.message;
      if (meta) meta.textContent = info.missing ? "模块未就绪" : "生成失败";
      toast(info.message, "error");
    }
  }

  async function verifyCitations() {
    const button = $("#citation-verify");
    const box = $("#citation-checks");
    const countsNode = $("#citation-counts");
    if (busy) return;
    busy = true;
    if (button) button.disabled = true;
    if (box) W.loading(box, "正在逐条核 DOI（Crossref / OpenAlex）…");
    if (countsNode) countsNode.textContent = "核引中…";
    try {
      const result = await api.post("/api/citations/verify", { project_id: W.projectId });
      const counts = (result && result.counts) || {};
      if (countsNode) countsNode.textContent = countsText(counts);
      const summary = STATUS_ORDER.filter((key) => counts[key])
        .map((key) => (STATUS_LABELS[key] || key) + " " + counts[key])
        .join(" · ");
      toast("核引完成" + (summary ? "：" + summary : "。"), "ok");
      await loadChecks();
    } catch (error) {
      toast(error.message, "error");
      if (countsNode) countsNode.textContent = "核引失败";
      if (box) W.showError(box, error, { retry: verifyCitations });
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }

  function countsText(counts) {
    const parts = STATUS_ORDER.filter((key) => counts && counts[key])
      .map((key) => (STATUS_LABELS[key] || key) + " " + counts[key]);
    return parts.length ? "最新结果：" + parts.join(" · ") : "还没有核引记录。";
  }

  async function loadChecks() {
    const box = $("#citation-checks");
    const countsNode = $("#citation-counts");
    if (!box) return;
    try {
      const checks = await api.get("/api/citations/checks?project_id=" + W.projectId);
      const list = Array.isArray(checks) ? checks : [];
      if (!list.length) {
        W.empty(
          box,
          "还没有核引记录。",
          "点「批量核引」逐条查 DOI；核不到会标红，不会静默通过。",
          ""
        );
        if (countsNode) countsNode.textContent = "还没有核引记录。";
        return;
      }
      const counts = {};
      list.forEach((item) => {
        const status = (item && item.status) || "error";
        counts[status] = (counts[status] || 0) + 1;
      });
      if (countsNode) countsNode.textContent = countsText(counts);
      box.innerHTML =
        '<table class="checks-table"><thead><tr>' +
        "<th>文献</th><th>状态</th><th>说明</th><th>核验时间</th>" +
        "</tr></thead><tbody>" +
        list
          .map((item) => {
            const status = item.status || "error";
            const title = item.title || "文献 #" + item.ref_id;
            return (
              "<tr>" +
              '<td><div class="ref-title">' + esc(title) + "</div>" +
              '<div class="ref-sub">#' + esc(item.ref_id) + "</div></td>" +
              '<td><span class="check-status ' + (STATUS_CLASSES[status] || "muted") + '">' +
              esc(STATUS_LABELS[status] || status) + "</span></td>" +
              "<td>" + esc(detailText(item.detail, status)) + "</td>" +
              '<td class="num">' + esc(window.fmtDate(item.checked_at)) + "</td>" +
              "</tr>"
            );
          })
          .join("") +
        "</tbody></table>";
    } catch (error) {
      W.showError(box, error, { retry: loadChecks });
      if (countsNode) countsNode.textContent = "读取核引记录失败";
    }
  }

  function detailText(detail, status) {
    if (!detail || (typeof detail === "object" && !Object.keys(detail).length)) {
      if (status === "no_doi") return "没有 DOI，无法自动核，请人工核对。";
      if (status === "verified") return "标题、年份与作者一致。";
      if (status === "not_found") return "Crossref / OpenAlex 均未找到。";
      if (status === "mismatch") return "字段与源记录不一致。";
      if (status === "error") return "核验过程出错，可重试。";
      return "";
    }
    if (typeof detail === "string") return detail;
    if (typeof detail !== "object") return String(detail);
    if (detail.reason) return String(detail.reason);
    if (detail.message) return String(detail.message);
    if (detail.mismatches) {
      const fields = Array.isArray(detail.mismatches)
        ? detail.mismatches
        : Object.keys(detail.mismatches);
      return "字段不一致：" + fields.join("、");
    }
    if (detail.tried) {
      const tried = Array.isArray(detail.tried) ? detail.tried : [detail.tried];
      return "已查：" + tried.join("、");
    }
    try {
      return JSON.stringify(detail).slice(0, 160);
    } catch (_) {
      return "";
    }
  }

  W.views.delivery = {
    mount,
    async show() {
      await loadGate();
      await loadChecks();
    },
  };
})();
