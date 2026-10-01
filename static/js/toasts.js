/* =========================================================
   Farm Irrigation Workbench — global Bootstrap toast helper
   ========================================================= */

(function () {
  "use strict";

  // icon per category
  const ICONS = {
    success: "✅",
    error:   "⛔",
    danger:  "⛔",
    warning: "⚠️",
    info:    "ℹ️"
  };

  // Bootstrap bg class per category
  const BG = {
    success: "text-bg-success",
    error:   "text-bg-danger",
    danger:  "text-bg-danger",
    warning: "text-bg-warning",
    info:    "text-bg-info"
  };

  // ---- core API ----
  window.showToast = function (message, category, opts) {
    opts = opts || {};
    category = category || "info";

    const container = document.getElementById("toast-container");
    if (!container) {
      console.warn("Toast container not found — falling back to alert");
      alert(message);
      return;
    }

    const delay = opts.delay != null ? opts.delay : 5000;

    const wrapper = document.createElement("div");
    wrapper.className = "toast " + (BG[category] || "text-bg-secondary");
    wrapper.setAttribute("role", "alert");
    wrapper.setAttribute("aria-live", "assertive");
    wrapper.setAttribute("aria-atomic", "true");
    wrapper.dataset.bsAutohide = delay > 0 ? "true" : "false";
    wrapper.dataset.bsDelay = String(delay);

    const icon = ICONS[category] || "•";

    wrapper.innerHTML = `
      <div class="d-flex align-items-start">
        <div class="toast-icon me-2">${icon}</div>
        <div class="toast-body flex-grow-1">${message}</div>
        <button type="button" class="btn-close btn-close-white ms-2 me-0"
                data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;

    container.appendChild(wrapper);

    const toast = new bootstrap.Toast(wrapper, {
      autohide: delay > 0,
      delay: delay
    });

    toast.show();

    wrapper.addEventListener("hidden.bs.toast", function () {
      wrapper.remove();
    });

    return toast;
  };

  // ---- convenience shorthands ----
  window.toastSuccess = (msg, d) => window.showToast(msg, "success", { delay: d });
  window.toastError   = (msg, d) => window.showToast(msg, "error",   { delay: d });
  window.toastWarning = (msg, d) => window.showToast(msg, "warning", { delay: d });
  window.toastInfo    = (msg, d) => window.showToast(msg, "info",    { delay: d });

  // ---- convert Flask flashes on page load ----
  document.addEventListener("DOMContentLoaded", function () {
    const box = document.getElementById("flash-data");
    if (!box) return;
    box.querySelectorAll("span[data-category]").forEach(function (el) {
      const cat = el.getAttribute("data-category");
      const msg = el.textContent.trim();
      if (msg) window.showToast(msg, cat, { delay: 5000 });
    });
    box.remove();
  });
})();