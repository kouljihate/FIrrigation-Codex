/* =========================================================
   Farm Irrigation Workbench — global modal helpers
   Replaces window.confirm() and window.alert() with Bootstrap modals
   ========================================================= */

(function () {
  "use strict";

  function getModal(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    return bootstrap.Modal.getOrCreateInstance(el);
  }

  /* ---------- CONFIRM ---------- */
  // Usage:
  //   appConfirm({
  //     titleEn: "Delete project",
  //     titleAr: "حذف المشروع",
  //     bodyEn:  "This cannot be undone.",
  //     bodyAr:  "لا يمكن التراجع عن هذا الإجراء.",
  //     okEn:    "Delete",
  //     okAr:    "حذف",
  //     cancelEn:"Cancel",
  //     cancelAr:"إلغاء",
  //     danger:  true,
  //     onOk:    function () { ... }   // called if user confirms
  //   });
  window.appConfirm = function (opts) {
    const o = Object.assign({
      titleEn: "Confirm",
      titleAr: "تأكيد",
      bodyEn:  "Are you sure?",
      bodyAr:  "هل أنت متأكد؟",
      okEn:    "Yes",
      okAr:    "نعم",
      cancelEn:"Cancel",
      cancelAr:"إلغاء",
      danger:  false,
      onOk:    null
    }, opts || {});

    const modalEl = document.getElementById("appConfirmModal");
    if (!modalEl) return;

    // fill content
    modalEl.querySelector(".modal-title .en").textContent = o.titleEn;
    modalEl.querySelector(".modal-title .ar").textContent = o.titleAr;
    modalEl.querySelector(".modal-body .en").textContent  = o.bodyEn;
    modalEl.querySelector(".modal-body .ar").textContent  = o.bodyAr;
    modalEl.querySelector(".js-ok .en").textContent       = o.okEn;
    modalEl.querySelector(".js-ok .ar").textContent       = o.okAr;
    modalEl.querySelector(".js-cancel .en").textContent   = o.cancelEn;
    modalEl.querySelector(".js-cancel .ar").textContent   = o.cancelAr;

    // danger styling
    modalEl.classList.toggle("danger", !!o.danger);

    // button styles
    const okBtn = modalEl.querySelector(".js-ok");
    okBtn.classList.remove("btn-success", "btn-danger", "btn-primary");
    okBtn.classList.add(o.danger ? "btn-danger" : "btn-success");

    // handler
    const prevOk = okBtn._appConfirmHandler;
    if (prevOk) okBtn.removeEventListener("click", prevOk);

    const handler = function () {
      getModal("appConfirmModal").hide();
      if (typeof o.onOk === "function") o.onOk();
    };
    okBtn.addEventListener("click", handler);
    okBtn._appConfirmHandler = handler;

    getModal("appConfirmModal").show();
  };

  /* ---------- ALERT ---------- */
  // Usage:
  //   appAlert({ titleEn:"Info", titleAr:"معلومة",
  //              bodyEn:"Saved.", bodyAr:"تم الحفظ." });
   /* ---------- ALERT (now a toast) ---------- */
  // Usage: appAlert({ bodyEn:"Saved.", bodyAr:"تم الحفظ.", category:"success" });
  window.appAlert = function (opts) {
    const o = Object.assign({
      bodyEn:   "",
      bodyAr:   "",
      category: "info",
      delay:    5000
    }, opts || {});

    // combine EN + AR in one line with a divider
    const text = (o.bodyEn && o.bodyAr)
      ? `${o.bodyEn} · ${o.bodyAr}`
      : (o.bodyEn || o.bodyAr || "");

    if (typeof window.showToast === "function") {
      window.showToast(text, o.category, { delay: o.delay });
    } else {
      alert(text);
    }
  };

  /* ---------- Auto-wire data-attributes ----------
     Any element with data-confirm-text-en (or _ar) or data-confirm-url
     will trigger appConfirm on click.
     <a href="/delete/1" data-confirm
        data-confirm-en="Delete project?"
        data-confirm-ar="حذف المشروع؟">Delete</a>
  */
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-confirm-url], [data-confirm]").forEach(function (el) {
      el.addEventListener("click", function (ev) {
        ev.preventDefault();

        const url     = el.getAttribute("data-confirm-url") || el.getAttribute("href");
        const bodyEn  = el.getAttribute("data-confirm-en") || "Are you sure?";
        const bodyAr  = el.getAttribute("data-confirm-ar") || "هل أنت متأكد؟";
        const titleEn = el.getAttribute("data-confirm-title-en") || "Confirm";
        const titleAr = el.getAttribute("data-confirm-title-ar") || "تأكيد";
        const okEn    = el.getAttribute("data-confirm-ok-en") || "Yes";
        const okAr    = el.getAttribute("data-confirm-ok-ar") || "نعم";
        const danger  = el.hasAttribute("data-confirm-danger");

        const form   = el.closest("form");
        const method = (el.getAttribute("data-confirm-method") || "GET").toUpperCase();

        appConfirm({
          titleEn, titleAr, bodyEn, bodyAr, okEn, okAr, danger,
          onOk: function () {
            if (form && method === "POST") {
              form.submit();
            } else if (url) {
              window.location.href = url;
            }
          }
        });
      });
    });
  });

})();