/* Wenshu API helper: local token, JSON errors, toast. */
(function () {
  const meta = document.querySelector('meta[name="wenshu-token"]');
  const token = meta ? meta.getAttribute("content") : "";

  async function request(method, path, body, options = {}) {
    const headers = Object.assign({ "X-Wenshu-Token": token }, options.headers || {});
    let payload;
    if (body instanceof FormData) {
      payload = body;
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const response = await fetch(path, {
      method,
      headers,
      body: payload,
      credentials: "same-origin",
      ...options,
    });
    if (!response.ok) {
      let message = `请求失败（${response.status}）`;
      let code = "http_error";
      let detail = null;
      const type = response.headers.get("content-type") || "";
      if (type.includes("application/json")) {
        try {
          const data = await response.json();
          if (data && data.error) {
            message = data.error.message || message;
            code = data.error.code || code;
            detail = data.error.detail;
          }
        } catch (_) { /* keep default */ }
      }
      const error = new Error(message);
      error.status = response.status;
      error.code = code;
      error.detail = detail;
      throw error;
    }
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) return response.json();
    return response;
  }

  const api = {
    token,
    request,
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body),
    put: (path, body) => request("PUT", path, body),
    patch: (path, body) => request("PATCH", path, body),
    del: (path) => request("DELETE", path),
    upload: (path, form) => request("POST", path, form),
    download: async (path, body, filename) => {
      const response = await request("POST", path, body);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "wenshu-export";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  };

  let toastTimer = null;
  function toast(message, kind = "") {
    const node = document.getElementById("toast");
    if (!node) return;
    node.textContent = message;
    node.className = "toast show " + kind;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.className = "toast " + kind; }, 3200);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function debounce(fn, wait) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  function fmtDate(value) {
    if (!value) return "";
    return String(value).replace("T", " ").slice(0, 16);
  }

  window.api = api;
  window.toast = toast;
  window.escapeHtml = escapeHtml;
  window.debounce = debounce;
  window.fmtDate = fmtDate;
})();
