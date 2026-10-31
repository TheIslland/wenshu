/* Dashboard + settings page behaviour. Workspace page is handled by workspace.js. */
(function () {
  function initDashboard() {
    const dialog = document.getElementById("new-project-dialog");
    const form = document.getElementById("new-project-form");
    if (!dialog || !form) return;

    const open = () => { if (typeof dialog.showModal === "function") dialog.showModal(); };
    ["open-new-project", "open-new-project-empty"].forEach((id) => {
      const button = document.getElementById(id);
      if (button) button.addEventListener("click", open);
    });
    const cancel = document.getElementById("cancel-new-project");
    if (cancel) cancel.addEventListener("click", () => dialog.close());

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      const payload = {
        name: String(data.get("name") || "").trim(),
        field: String(data.get("field") || "").trim(),
        question: String(data.get("question") || "").trim(),
      };
      if (!payload.name) { toast("项目名不能为空。", "error"); return; }
      const submit = form.querySelector('button[type="submit"]');
      submit.disabled = true;
      try {
        const project = await api.post("/api/projects", payload);
        location.href = `/p/${project.id}`;
      } catch (error) {
        toast(error.message, "error");
      } finally {
        submit.disabled = false;
      }
    });
  }

  async function initSettings() {
    const form = document.getElementById("llm-form");
    if (!form) return;
    const provider = document.getElementById("llm-provider");
    const baseUrl = document.getElementById("llm-base-url");
    const model = document.getElementById("llm-model");
    const apiKey = document.getElementById("llm-api-key");
    const keyHint = document.getElementById("llm-key-hint");
    const searchForm = document.getElementById("search-form-settings");

    let presets = {};
    try {
      const data = await api.get("/api/settings");
      presets = data.presets || {};
      for (const [key, preset] of Object.entries(presets)) {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = preset.label || key;
        provider.appendChild(option);
      }
      provider.value = data.llm.provider || "deepseek";
      baseUrl.value = data.llm.base_url || "";
      model.value = data.llm.model || "";
      keyHint.textContent = data.llm.has_key
        ? `已保存 key（${data.llm.key_hint}）。留空不修改。`
        : "还没有保存 key。";
      const mailto = document.getElementById("search-mailto");
      if (mailto) mailto.value = (data.search && data.search.mailto) || "";
      const dataDir = document.getElementById("data-dir");
      if (dataDir) dataDir.textContent = data.data_dir || "";
    } catch (error) {
      toast(error.message, "error");
    }

    provider.addEventListener("change", () => {
      const preset = presets[provider.value];
      if (preset) {
        baseUrl.value = preset.base_url || "";
        model.value = preset.model || "";
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const result = await api.put("/api/settings", {
          llm: {
            provider: provider.value,
            base_url: baseUrl.value.trim(),
            model: model.value.trim(),
            api_key: apiKey.value.trim() || null,
          },
        });
        apiKey.value = "";
        keyHint.textContent = result.llm.has_key
          ? `已保存 key（${result.llm.key_hint}）。留空不修改。`
          : "还没有保存 key。";
        toast("已保存。", "ok");
      } catch (error) {
        toast(error.message, "error");
      }
    });

    const test = document.getElementById("test-llm");
    if (test) test.addEventListener("click", async () => {
      test.disabled = true;
      try {
        const result = await api.post("/api/settings/test-llm", {});
        toast(`模型可用（${result.latency_ms} ms）`, "ok");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        test.disabled = false;
      }
    });

    if (searchForm) searchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api.put("/api/settings", {
          search: {
            mailto: document.getElementById("search-mailto").value.trim(),
            s2_api_key: document.getElementById("s2-api-key").value.trim() || null,
          },
        });
        document.getElementById("s2-api-key").value = "";
        toast("检索设置已保存。", "ok");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  }

  initDashboard();
  initSettings();
})();
