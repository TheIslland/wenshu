/* 段落调整：压缩 / 扩写 / 重排 / 补论证；三色 diff、reason、gaps。 */
(function () {
  const W = (window.Wenshu = window.Wenshu || {});
  W.views = W.views || {};
  let view = null;

  W.views.paragraphs = {
    mount(panel) {
      view = W.createRewritePanel(panel, {
        input: "#paragraph-input",
        run: "#paragraph-run",
        result: "#paragraph-result",
        loadSelection: "#paragraph-load-selection",
        endpoint: "/api/paragraphs/transform",
        loading: "正在调整段落…",
        acceptLabel: "接受调段",
        buildBody(text, ctx) {
          const context = W.contextAround(200);
          const opNode = panel.querySelector("#paragraph-op");
          const roleNode = panel.querySelector("#paragraph-role");
          return {
            text,
            op: opNode ? opNode.value : "compress",
            role: roleNode ? roleNode.value : "analysis",
            max_delta: 0.2,
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
