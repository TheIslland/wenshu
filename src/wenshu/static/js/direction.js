/* 研究方向：检索统计 + 3–5 张问题卡（证据边界明确）。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  const esc = (value) => window.escapeHtml(value);
  const toast = window.toast;

  let panelEl = null;
  let bound = false;
  let refTitles = new Map();

  const $ = (selector) => (panelEl ? panelEl.querySelector(selector) : null);

  function mount(panel) {
    panelEl = panel;
    if (bound) return;
    bound = true;
    const run = $("#direction-run");
    if (run) run.addEventListener("click", explore);
    const topic = $("#direction-topic");
    if (topic) {
      topic.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          explore();
        }
      });
    }
    loadRefTitles();
  }

  async function loadRefTitles() {
    try {
      const refs = await api.get("/api/refs?project_id=" + W.projectId);
      if (Array.isArray(refs)) {
        refTitles = new Map(refs.map((ref) => [Number(ref.id), ref.title || ""]));
      }
    } catch (_) {
      /* 文献库还没就绪时问题卡仍可显示 */
    }
  }

  const SCOPE_LABELS = {
    project: "本项目",
    library: "本地库",
    openalex: "OpenAlex",
    crossref: "Crossref",
    semantic_scholar: "Semantic Scholar",
    arxiv: "arXiv",
  };

  function statsChips(stats) {
    if (!stats || typeof stats !== "object") return "";
    const chips = [];
    const add = (label, value) => {
      if (value == null || value === "" || (Array.isArray(value) && !value.length)) return;
      const display = Array.isArray(value) ? value.slice(0, 4).join("、") : String(value);
      chips.push(
        '<span class="stat-chip">' + esc(label) + "<b>" + esc(display) + "</b></span>"
      );
    };
    add("总产出", stats.total);
    add("有摘要", stats.with_abstract);
    if (stats.year_range) {
      const range = Array.isArray(stats.year_range)
        ? stats.year_range.join("–")
        : typeof stats.year_range === "object"
          ? [stats.year_range.from, stats.year_range.to].filter(Boolean).join("–")
          : stats.year_range;
      add("年份范围", range);
    }
    if (stats.scope) add("统计范围", SCOPE_LABELS[stats.scope] || stats.scope);
    if (Array.isArray(stats.top_venues) && stats.top_venues.length) {
      add(
        "高频期刊",
        stats.top_venues.map((venue) => (typeof venue === "string" ? venue : venue.name || venue.venue))
      );
    }
    if (Array.isArray(stats.top_authors) && stats.top_authors.length) {
      add(
        "高频作者",
        stats.top_authors.map((author) => (typeof author === "string" ? author : author.name || author.author))
      );
    }
    return chips.length ? chips.join("") : "";
  }

  function evidenceChips(card) {
    const ids = Array.isArray(card.evidence_refs) ? card.evidence_refs : [];
    const notes = (Array.isArray(card.evidence_notes) ? card.evidence_notes : [])
      .filter(Boolean)
      .map(String);
    if (!ids.length) {
      const note = notes.join("；") || "待检索";
      return (
        '<div class="card-evidence"><span class="muted">支撑文献：' +
        esc(note) +
        "</span></div>"
      );
    }
    const chips = ids
      .map((id) => {
        const title = refTitles.get(Number(id));
        const label = title || "#" + id;
        return (
          '<span class="evidence-ref" title="' + esc(title || "文献") + '">' +
          esc(label) +
          "</span>"
        );
      })
      .join("");
    const noteText = notes
      .filter((note) => note !== "待检索")
      .join("；");
    return (
      '<div class="card-evidence"><span class="muted">支撑文献：</span>' +
      chips +
      "</div>" +
      (noteText ? '<p class="card-extra">' + esc(noteText) + "</p>" : "")
    );
  }

  function renderCards(cards) {
    const box = $("#direction-cards");
    if (!box) return;
    if (!Array.isArray(cards) || !cards.length) {
      W.empty(
        box,
        "还没有问题卡。",
        "换一个更具体的现象 / 机制关键词，或先入库几篇文献再试。",
        ""
      );
      return;
    }
    box.innerHTML = cards
      .map((card) => {
        const rows = [
          ["既有裂缝", card.gap],
          ["所需材料", card.materials],
          ["可行方法", card.method],
          ["主要风险", card.risk],
          ["难度", card.difficulty],
          ["新颖度", card.novelty],
        ].filter(([, value]) => value != null && String(value).trim());
        return (
          '<article class="card">' +
          '<h3 class="card-q">' + esc(card.question || "（未命名问题）") + "</h3>" +
          (rows.length
            ? '<dl class="card-kv">' +
              rows
                .map(
                  ([label, value]) =>
                    "<dt>" + esc(label) + "</dt><dd>" + esc(String(value)) + "</dd>"
                )
                .join("") +
              "</dl>"
            : "") +
          evidenceChips(card) +
          "</article>"
        );
      })
      .join("");
  }

  async function explore() {
    const topicNode = $("#direction-topic");
    const topic = topicNode ? topicNode.value.trim() : "";
    if (!topic) {
      toast("先填领域 / 现象 / 理论关键词。", "error");
      return;
    }
    const run = $("#direction-run");
    if (run) run.disabled = true;
    const cardsBox = $("#direction-cards");
    const statsBox = $("#direction-stats");
    W.loading(cardsBox, "正在汇总检索统计与生成问题卡…");
    if (statsBox) statsBox.innerHTML = "";
    const meta = $("#direction-meta");
    if (meta) meta.textContent = "检索中…";
    try {
      const payload = {
        topic,
        project_id: W.projectId,
        years: Number((($("#direction-years") || {}).value) || 10),
      };
      const language = (($("#direction-language") || {}).value || "").trim();
      if (language) payload.language = language;
      if (!refTitles.size) await loadRefTitles();
      const data = await api.post("/api/direction/explore", payload);
      renderCards(data && data.cards);
      if (statsBox) statsBox.innerHTML = statsChips(data && data.stats);
      if (meta) {
        meta.textContent =
          (data && data.llm_used ? "LLM 生成" : "内置问题模板 / 规则") +
          (data && data.warnings && data.warnings.length ? " · " + data.warnings.length + " 条提示" : "");
      }
      if (data && Array.isArray(data.warnings) && data.warnings.length) {
        cardsBox.insertAdjacentHTML("beforeend", W.warningsHtml(data.warnings));
      }
    } catch (error) {
      W.showError(cardsBox, error, { retry: explore });
      if (meta) meta.textContent = "生成失败";
    } finally {
      if (run) run.disabled = false;
    }
  }

  W.views.direction = {
    mount,
    async show() {
      await loadRefTitles();
    },
  };
})();
