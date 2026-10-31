/* 风格体检：风险仪表、证据 span 高亮、安全修正 diff、LLM 重写三色 diff。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  const SEVERITY_LABEL = { info: "提示", warn: "中", high: "高" };
  const SEVERITY_CLASS = { info: "info", warn: "medium", high: "high" };
  const METRIC_LABELS = {
    chars: "总字符",
    units: "计分单位",
    visible_chars: "可见字符",
    paragraphs: "段数",
    sentences: "句数",
    sentence_mean: "平均句长",
    sentence_cv: "句长变异",
    sentence_length_cv: "句长变异",
    paragraph_cv: "段长变异",
    paragraph_len_cv: "段长变异",
    same_len_run: "连续同长句",
    connectives: "连接词数",
    connective_per_k: "连接词密度/千字",
    connective_density: "连接词密度",
    connective_ttr: "连接词多样性",
    boilerplate: "套话数",
    boilerplate_per_k: "套话密度/千字",
    inflation: "意义拔高",
    inflation_per_k: "拔高密度/千字",
    pseudo_depth_per_k: "假深刻否定/千字",
    dash_per_k: "破折号/千字",
    quote_per_k: "装饰引号/千字",
    vague_verb_per_k: "虚化动词/千字",
    nominalization_per_k: "性化度/千字",
    anchor_per_100: "具体锚点/百字",
    max_de: "单句最多「的」",
    de_chain: "「的」字链",
    four_char_runs: "四字连排",
    four_char_density: "四字连排/千字",
    four_char_run: "四字连排",
    cliche_count: "套话数",
    elevation_density: "意义拔高",
    negation_pattern: "假深刻否定",
    dash_density: "破折号密度",
    quote_density: "引号密度",
    nominalization_density: "虚化动词",
    specificity_anchor: "具体性锚点",
    specificity_density: "具体性密度",
  };

  let panelEl = null;
  let bound = false;
  let reportEl = null;
  let source = { text: "", target: null };
  let lastFix = null;
  let lastFixFindings = [];
  let lastRewrite = null;
  let busy = false;

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;
    reportEl = $("#style-report");

    const analyzeDoc = $("#analyze-document");
    if (analyzeDoc) {
      analyzeDoc.addEventListener("click", () => analyze(true));
    }
    const analyzeText = $("#analyze-text");
    if (analyzeText) {
      analyzeText.addEventListener("click", () => analyze(false));
    }
    if (reportEl) reportEl.addEventListener("click", onReportClick);
  }

  function useLlm() {
    const toggle = $("#style-use-llm");
    return !!(toggle && toggle.checked && !toggle.disabled);
  }

  function targetHint(fromDocument) {
    const hint = $("#style-target-hint");
    if (!hint) return;
    const title = W.state.current ? "《" + W.state.current.title + "》" : "当前文档";
    if (fromDocument) {
      hint.textContent = "当前文档" + title + "（" + source.text.length + " 字）";
      return;
    }
    const writable = source.target ? "可写回写作页" : "只显示结果，不写回";
    hint.textContent = "下方文本（" + source.text.length + " 字）· " + writable;
  }

  function setTarget(text) {
    const input = $("#style-input");
    if (input) input.value = text || "";
    source = { text: text || "", target: W.state.editTarget || null };
    targetHint(false);
  }

  function setBusy(value) {
    busy = value;
    ["#analyze-document", "#analyze-text"].forEach((selector) => {
      const button = $(selector);
      if (button) button.disabled = value;
    });
  }

  async function analyze(fromDocument) {
    if (busy) return;
    let text = "";
    if (fromDocument) {
      text = W.editorText ? W.editorText() : "";
      if (!text.trim()) {
        toast("当前文档还是空的，先写一点。", "error");
        return;
      }
      source = {
        text,
        target: W.state.current
          ? { documentId: W.state.current.id, start: 0, end: text.length, original: text }
          : null,
      };
      W.setEditTarget(source.target);
    } else {
      const input = $("#style-input");
      text = input ? input.value : "";
      if (!text.trim()) {
        text = W.editorText ? W.editorText() : "";
      }
      if (!text.trim()) {
        toast("先粘贴一段文字，或在写作页写正文。", "error");
        return;
      }
      const target =
        W.state.editTarget && W.state.editTarget.original === text
          ? W.state.editTarget
          : W.targetForText(text);
      source = { text, target };
      W.setEditTarget(target);
    }
    targetHint(fromDocument);
    setBusy(true);
    if (reportEl) W.loading(reportEl, "正在跑规则体检…");
    try {
      const data = await api.post("/api/style/analyze", {
        text: source.text,
        project_id: W.projectId,
        use_llm: useLlm(),
      });
      renderReport(data || {});
    } catch (error) {
      W.showError(reportEl, error, { retry: () => analyze(fromDocument) });
    } finally {
      setBusy(false);
    }
  }

  function scoreOf(report) {
    const score = Number(report && report.score);
    if (!Number.isFinite(score)) return 0;
    return Math.max(0, Math.min(100, Math.round(score)));
  }

  function levelOf(report) {
    const level = report && report.level;
    return level === "high" || level === "medium" ? level : "low";
  }

  function renderGauge(score) {
    const radius = 44;
    const circumference = 2 * Math.PI * radius;
    const dash = (score / 100) * circumference;
    return (
      '<div class="gauge" aria-hidden="true"><svg viewBox="0 0 104 104">' +
      '<circle class="gauge-track" cx="52" cy="52" r="' + radius + '"></circle>' +
      '<circle class="gauge-value" cx="52" cy="52" r="' + radius + '" ' +
      'stroke-dasharray="' + dash.toFixed(2) + " " + (circumference - dash).toFixed(2) + '"></circle>' +
      "</svg><div class=\"gauge-num\">" + score + "</div></div>"
    );
  }

  function metricRows(metrics) {
    if (!metrics || typeof metrics !== "object") return "";
    const entries = Object.entries(metrics)
      .filter(([key]) => METRIC_LABELS[key])
      .slice(0, 12);
    if (!entries.length) return "";
    return (
      '<div class="metrics-grid">' +
      entries
        .map(([key, value]) => {
          const label = METRIC_LABELS[key];
          const display =
            typeof value === "number"
              ? Number.isInteger(value)
                ? String(value)
                : value.toFixed(2)
              : esc(String(value));
          return '<span class="metric">' + esc(label) + " <b>" + display + "</b></span>";
        })
        .join("") +
      "</div>"
    );
  }

  function highlightText(text, findings) {
    const limit = 12000;
    const visible = text.slice(0, limit);
    const ranges = findings
      .map((finding, index) => ({
        index,
        start: Math.max(0, Number(finding.start) || 0),
        end: Math.min(visible.length, Number(finding.end) || 0),
        severity: finding.severity || "warn",
      }))
      .filter((range, index) => range.end > range.start && range.start < limit)
      .sort((a, b) => a.start - b.start || a.end - b.end);
    const kept = [];
    let cursor = 0;
    ranges.forEach((range) => {
      if (range.start < cursor) return;
      kept.push(range);
      cursor = range.end;
    });
    let html = "";
    let position = 0;
    kept.forEach((range) => {
      if (range.start > position) html += esc(visible.slice(position, range.start));
      const cls = range.severity === "high" ? "hl-high" : range.severity === "info" ? "hl-info" : "";
      html +=
        '<mark class="' + cls + '" data-finding-index="' + range.index + '">' +
        esc(visible.slice(range.start, range.end)) +
        "</mark>";
      position = range.end;
    });
    if (position < visible.length) html += esc(visible.slice(position));
    if (text.length > limit) {
      html += '<span class="muted">…（共 ' + text.length + " 字，只高亮前 " + limit + " 字）</span>";
    }
    return html;
  }

  function renderReport(report) {
    if (!reportEl) return;
    const score = scoreOf(report);
    const level = levelOf(report);
    const levelLabel = level === "high" ? "高" : level === "medium" ? "中" : "低";
    const findings = Array.isArray(report.findings) ? report.findings : [];
    const autoFixable = findings.filter((finding) => finding && finding.auto_fixable);
    const warnings = Array.isArray(report.warnings) ? report.warnings : [];
    const summary =
      report.summary ||
      (findings.length
        ? "命中 " + findings.length + " 条风格规则；分数越高，模板化痕迹越明显。"
        : "没有命中规则。分数只描述风格风险，不代表文本质量或作者身份。");
    const badges = [];
    badges.push(
      '<span class="risk-badge ' + level + '">风格风险 ' + levelLabel + "</span>"
    );
    badges.push(
      '<span class="risk-badge info">' + (report.baseline_used ? "个人基线" : "默认阈值") + "</span>"
    );
    badges.push(
      '<span class="risk-badge info">' + (report.llm_used ? "LLM 复审已用" : "规则引擎") + "</span>"
    );

    const evidence =
      findings.some((finding) => Number(finding.end) > Number(finding.start))
        ? '<details class="evidence-toggle" open><summary>证据高亮 · 点击色块跳到对应条目</summary>' +
          '<div class="evidence-preview">' + highlightText(source.text, findings) + "</div></details>"
        : "";

    const cards = findings.length
      ? findings
          .map((finding, index) => {
            const severity = SEVERITY_CLASS[finding.severity] || "medium";
            const sevKey = finding.severity === "high" ? "high" : finding.severity === "info" ? "info" : "warn";
            const actions = [
              finding.auto_fixable
                ? '<button class="btn mini ghost" type="button" data-finding-action="fix-one" data-index="' +
                  index + '">仅修正这条</button>'
                : "",
              '<button class="btn mini ghost" type="button" data-finding-action="rewrite-one" data-index="' +
                index + '">带这条线索重写</button>',
            ].join("");
            return (
              '<article class="finding finding-' + severity + '" data-finding-card="' + index + '">' +
              '<div class="finding-top">' +
              '<span class="finding-name">' + esc(finding.name || finding.rule_id || "规则") + "</span>" +
              '<span class="sev ' + sevKey + '">' + esc(SEVERITY_LABEL[finding.severity] || "中") + "</span>" +
              '<span class="finding-loc">' + esc(finding.rule_id || "") +
              (Number(finding.end) > Number(finding.start)
                ? " · [" + esc(finding.start) + "–" + esc(finding.end) + "]"
                : "") +
              "</span></div>" +
              (finding.text ? '<div class="finding-quote">' + esc(finding.text) + "</div>" : "") +
              (finding.message ? '<p class="finding-msg">' + esc(finding.message) + "</p>" : "") +
              (finding.suggestion
                ? '<p class="finding-suggestion">' + esc(finding.suggestion) + "</p>"
                : "") +
              '<div class="finding-actions">' + actions + "</div></article>"
            );
          })
          .join("")
      : '<div class="empty compact"><p>没有命中规则。</p><p class="muted">继续写；具体性不足的段落不会被自动「补材料」，只会提示你补。</p></div>';

    reportEl.className = "report lvl-" + level;
    reportEl.innerHTML =
      '<div class="report-head">' +
      renderGauge(score) +
      '<div class="report-summary"><h3>风格风险分 ' + score + " / 100</h3>" +
      '<p class="muted">' + badges.join("") + "</p>" +
      "<p>" + esc(summary) + "</p>" +
      metricRows(report.metrics) +
      "</div></div>" +
      W.warningsHtml(warnings) +
      evidence +
      '<div class="section-label">规则命中 <small>' + findings.length + " 条 · 证据按原文位置标注</small></div>" +
      cards +
      '<div class="section-label">安全修正 <small>只删套话、还原虚化动词、改标点；每条可核</small></div>' +
      '<div class="toolbar">' +
      '<button class="btn" type="button" data-style-action="fix"' +
      (autoFixable.length ? "" : " disabled") + ">预览安全修正" +
      (autoFixable.length ? "（" + autoFixable.length + " 条可自动）" : "") + "</button>" +
      '<button class="btn ghost" type="button" data-style-action="rewrite">LLM 重写这段</button>' +
      '<span class="muted">任何改写都会重新过规则；引入新问题会被拒绝。</span>' +
      "</div>" +
      '<div id="style-fix-result" class="rewrite-result"></div>' +
      '<div id="style-rewrite-result" class="rewrite-result"></div>';

    reportEl._wenshuFindings = findings;
    lastFix = null;
    lastRewrite = null;
    reportEl.querySelectorAll(".evidence-preview mark").forEach((mark) => {
      mark.addEventListener("click", () => {
        const index = mark.dataset.findingIndex;
        const card = reportEl.querySelector('[data-finding-card="' + index + '"]');
        if (!card) return;
        card.classList.add("highlighted");
        card.scrollIntoView({ block: "center", behavior: "smooth" });
        setTimeout(() => card.classList.remove("highlighted"), 1600);
      });
    });
  }

  function findingsNow() {
    return (reportEl && reportEl._wenshuFindings) || [];
  }

  async function runFix(findings) {
    const container = $("#style-fix-result");
    if (!container) return;
    const selected = Array.isArray(findings) ? findings : findingsNow();
    if (!selected.length) {
      toast("没有可自动修正的条目。", "error");
      return;
    }
    const acceptable = selected.filter((finding) => finding && finding.auto_fixable);
    if (!acceptable.length) {
      toast("这些命中需要作者确认，不能自动修正。", "error");
      return;
    }
    W.loading(container, "正在生成安全修正…");
    lastFixFindings = acceptable;
    try {
      const data = await api.post("/api/style/fix", {
        text: source.text,
        findings: acceptable,
      });
      const view = Object.assign({}, data);
      view.original = source.text;
      if (!Array.isArray(view.ops) && Array.isArray(view.applied)) {
        view.ops = view.applied.map((item) =>
          [item.rule_id, item.before, item.after]
            .filter((part) => part != null && part !== "")
            .join("：")
        );
      }
      lastFix = { data: view };
      W.renderRewrite(container, view, { text: source.text });
    } catch (error) {
      W.showError(container, error, { retry: () => runFix(acceptable) });
    }
  }

  async function runRewrite(finding) {
    const container = $("#style-rewrite-result");
    if (!container) return;
    const modeNode = $("#style-mode");
    const mode = modeNode ? modeNode.value : "academic";
    const instruction = finding
      ? "只针对这条问题改写：" + (finding.name || finding.rule_id || "") + "。" +
        (finding.suggestion || finding.message || "")
      : "";
    W.loading(container, "正在请求模型改写…");
    try {
      const data = await api.post("/api/style/rewrite", {
        text: source.text,
        mode,
        instruction,
        project_id: W.projectId,
        use_llm: true,
      });
      const view = Object.assign({}, data);
      if (!view.original) view.original = source.text;
      lastRewrite = { data: view, source: source.text };
      W.renderRewrite(container, view, { text: source.text });
      if (Array.isArray(view.warnings) && view.warnings.length) {
        container.insertAdjacentHTML("beforeend", W.warningsHtml(view.warnings));
      }
    } catch (error) {
      W.showError(container, error, { retry: () => runRewrite(finding) });
    }
  }

  function acceptFix() {
    if (!lastFix) return;
    W.setEditTarget(
      source.target && source.target.original === source.text
        ? source.target
        : W.targetForText(source.text)
    );
    W.applyRevision(lastFix.data.revised, "接受安全修正");
  }

  function acceptRewrite() {
    if (!lastRewrite) return;
    const view = lastRewrite.data;
    const original = String(view.original || lastRewrite.source || "");
    let target = null;
    if (original === source.text) {
      target =
        source.target && source.target.original === source.text
          ? source.target
          : W.targetForText(source.text);
    } else {
      target = W.targetForText(original);
    }
    W.setEditTarget(target);
    W.applyRevision(view.revised, "接受 LLM 改写");
  }

  function onReportClick(event) {
    const rewriteAction = event.target.closest("[data-rewrite-action]");
    if (rewriteAction && reportEl.contains(rewriteAction)) {
      const action = rewriteAction.dataset.rewriteAction;
      const container = rewriteAction.closest(".rewrite-result");
      const isFix = container && container.id === "style-fix-result";
      if (action === "accept") {
        if (isFix) acceptFix();
        else acceptRewrite();
      } else if (action === "reject") {
        if (container) container.innerHTML = "";
        toast("已拒绝这次改写，原文未动。", "ok");
      } else if (action === "retry") {
        if (isFix) runFix(lastFixFindings);
        else runRewrite();
      } else if (action === "copy") {
        const data = isFix ? lastFix && lastFix.data : lastRewrite && lastRewrite.data;
        if (data) W.copy(data.revised);
      }
      return;
    }
    const findingAction = event.target.closest("[data-finding-action]");
    if (findingAction) {
      const index = Number(findingAction.dataset.index);
      const finding = findingsNow()[index];
      if (findingAction.dataset.findingAction === "fix-one" && finding) runFix([finding]);
      else if (findingAction.dataset.findingAction === "rewrite-one" && finding) runRewrite(finding);
      return;
    }
    const styleAction = event.target.closest("[data-style-action]");
    if (styleAction) {
      if (styleAction.dataset.styleAction === "fix") runFix();
      else if (styleAction.dataset.styleAction === "rewrite") runRewrite();
    }
  }

  W.views.style = {
    mount,
    async show() {
      W.refreshLlmHints();
    },
    setTarget,
  };
})();
