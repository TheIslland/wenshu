/* 文笔润色：模式、三色 diff、修改理由、接受/拒绝/再来一版、gaps。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  let view = null;

  W.views.polish = {
    mount(panel) {
      view = W.createRewritePanel(panel, {
        input: "#polish-input",
        run: "#polish-run",
        result: "#polish-result",
        mode: "#polish-mode",
        loadSelection: "#polish-load-selection",
        endpoint: "/api/polish",
        loading: "正在润色…",
        acceptLabel: "接受润色",
        buildBody(text, ctx) {
          const context = W.contextAround(200);
          return {
            text,
            mode: ctx.mode || "academic",
            context_before: context.before,
            context_after: context.after,
            project_id: W.projectId,
            use_llm: true,
          };
        },
      });
    },
    async show() {
      W.refreshLlmHints();
    },
    setTarget(text) {
      if (view) view.setTarget(text);
    },
  };
})();
