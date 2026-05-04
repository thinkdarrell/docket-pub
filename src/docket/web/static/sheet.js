/* docket.pub — mobile sheet behavior
 *
 * Plan A (lightweight launcher): full-screen bottom sheet via native <dialog>.
 *   - Opens from "View source" pill, citation chips, and after any HTMX rail swap.
 *   - Body scroll locked while open.
 *   - Esc key + backdrop tap + close button dismiss (Esc + Android-back come free with <dialog>).
 *   - Content is mirrored from #source-rail into #source-sheet-body so existing HTMX targets
 *     don't need to change.
 *
 * Footer accordion + More-sheet share helpers from this file.
 *
 * Snap points and scroll-sync (Plan B) are NOT included — they belong on a follow-on branch
 * so the v1 sheet stays a clean modal.
 */

(function () {
  'use strict';

  var MOBILE_QUERY = '(max-width: 768px)';
  var BODY_LOCK_CLASS = 'source-sheet-open';

  // Captured at init — the page-context default rail content (e.g. on city.html
  // it's the city-level rail; on meeting_detail it's the meeting rail). Used
  // when the user taps the "View source" pill so the sheet always reflects
  // page-level provenance rather than whatever item was last tapped.
  var initialRailHTML = null;

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  // ── Generic dialog open/close with body-scroll lock ─────────────────────────
  function openDialog(dialog) {
    if (!dialog || dialog.open) return;
    if (typeof dialog.showModal === 'function') {
      try { dialog.showModal(); }
      catch (_) { dialog.setAttribute('open', ''); }
    } else {
      dialog.setAttribute('open', '');
    }
    document.body.classList.add(BODY_LOCK_CLASS);
  }

  function closeDialog(dialog) {
    if (!dialog || !dialog.open) {
      document.body.classList.remove(BODY_LOCK_CLASS);
      return;
    }
    if (typeof dialog.close === 'function') {
      try { dialog.close(); } catch (_) { dialog.removeAttribute('open'); }
    } else {
      dialog.removeAttribute('open');
    }
    document.body.classList.remove(BODY_LOCK_CLASS);
  }

  // ── Mirror desktop rail → mobile sheet body ─────────────────────────────────
  function mirrorRailToSheet() {
    var rail = document.getElementById('source-rail');
    var body = document.getElementById('source-sheet-body');
    if (rail && body) body.innerHTML = rail.innerHTML;
  }

  // ── Wire source-sheet (the data-honesty rail) ───────────────────────────────
  function wireSourceSheet() {
    var sheet = document.getElementById('source-sheet');
    if (!sheet) return;

    // Backdrop click: <dialog>'s ::backdrop receives clicks ON the dialog itself.
    // Distinguish backdrop vs. inner content by comparing event.target.
    sheet.addEventListener('click', function (e) {
      if (e.target === sheet) closeDialog(sheet);
    });

    // Close button
    sheet.querySelectorAll('[data-sheet-close]').forEach(function (btn) {
      btn.addEventListener('click', function () { closeDialog(sheet); });
    });

    // Drag-handle tap also closes (full drag gesture is Plan B).
    sheet.querySelectorAll('[data-sheet-handle]').forEach(function (h) {
      h.addEventListener('click', function () { closeDialog(sheet); });
    });

    // ── The "View source" pill ──
    // ALWAYS shows the page-level default rail (initial content captured at load),
    // not whatever item was last tapped. Tapping the pill resets sheet body to
    // the page's source-of-truth view and opens the sheet.
    document.querySelectorAll('[data-sheet-trigger]').forEach(function (trigger) {
      trigger.addEventListener('click', function (e) {
        if (!isMobile()) return; // desktop already shows the rail
        e.preventDefault();
        var body = document.getElementById('source-sheet-body');
        if (body && initialRailHTML !== null) body.innerHTML = initialRailHTML;
        openDialog(sheet);
      });
    });

    // Citation chips (`.cite`) on mobile open the sheet at the current rail content.
    document.addEventListener('click', function (e) {
      var cite = e.target.closest && e.target.closest('.cite');
      if (!cite || !isMobile()) return;
      mirrorRailToSheet();
      openDialog(sheet);
    });

    // ── Mobile click interception for HTMX rail-swap triggers ──
    // On mobile, taps on elements that target #source-rail with HTMX should:
    //   (a) NAVIGATE if the element has an href (mobile users want to go to the thing)
    //   (b) Otherwise, open the sheet with that item's source content
    // This runs in CAPTURE phase so it beats HTMX's own click handler.
    document.addEventListener('click', function (e) {
      if (!isMobile()) return;
      var trigger = e.target.closest && e.target.closest('[hx-target="#source-rail"]');
      if (!trigger) return;
      var href = trigger.getAttribute('href');
      if (href && href !== '#') {
        // Navigate — let HTMX NOT fire by stopping at capture phase
        e.preventDefault();
        e.stopImmediatePropagation();
        window.location.href = href;
        return;
      }
      // No href → let HTMX swap fire; the afterSwap handler below will open the sheet.
    }, true);

    // After any HTMX swap that targeted #source-rail (only happens on mobile for
    // hrefless triggers thanks to the interceptor above), open the sheet.
    document.body.addEventListener('htmx:afterSwap', function (e) {
      var t = e.detail && e.detail.target;
      if (!t || t.id !== 'source-rail') return;
      mirrorRailToSheet();
      if (isMobile()) openDialog(sheet);
    });

    // Reset body lock when leaving mobile width while sheet was open.
    var mq = window.matchMedia(MOBILE_QUERY);
    var onChange = function (ev) {
      if (!ev.matches && sheet.open) closeDialog(sheet);
    };
    if (typeof mq.addEventListener === 'function') mq.addEventListener('change', onChange);
    else if (typeof mq.addListener === 'function') mq.addListener(onChange);

    // Native close (Esc, Android back) — clear body lock.
    sheet.addEventListener('close', function () {
      document.body.classList.remove(BODY_LOCK_CLASS);
    });
  }

  // ── Wire More-sheet (bottom-tabs "More") ────────────────────────────────────
  function wireMoreSheet() {
    var moreSheet = document.getElementById('more-sheet');
    if (!moreSheet) return;

    moreSheet.addEventListener('click', function (e) {
      if (e.target === moreSheet) closeDialog(moreSheet);
    });
    moreSheet.querySelectorAll('[data-sheet-close]').forEach(function (btn) {
      btn.addEventListener('click', function () { closeDialog(moreSheet); });
    });
    moreSheet.addEventListener('close', function () {
      document.body.classList.remove(BODY_LOCK_CLASS);
    });

    document.querySelectorAll('[data-more-trigger]').forEach(function (trigger) {
      trigger.addEventListener('click', function (e) {
        e.preventDefault();
        openDialog(moreSheet);
      });
    });
  }

  // ── Footer accordion (mobile-only) ──────────────────────────────────────────
  function wireFooterAccordion() {
    var cols = document.querySelectorAll('.footnote-col');
    if (!cols.length) return;
    cols.forEach(function (col, i) {
      // First column open by default, rest closed.
      col.setAttribute('data-open', i === 0 ? 'true' : 'false');
      var head = col.querySelector('.t-eyebrow');
      if (!head) return;
      head.setAttribute('role', 'button');
      head.setAttribute('tabindex', '0');
      var toggle = function () {
        if (!isMobile()) return; // desktop renders all columns expanded
        var open = col.getAttribute('data-open') === 'true';
        col.setAttribute('data-open', open ? 'false' : 'true');
      };
      head.addEventListener('click', toggle);
      head.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggle();
        }
      });
    });
  }

  // ── Mobile search button → route to /search ─────────────────────────────────
  function wireMobileSearch() {
    document.querySelectorAll('.mobile-search-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var url = btn.getAttribute('data-href') || '/search';
        window.location.href = url;
      });
    });
  }

  function init() {
    // Capture the initial (page-context) rail content BEFORE any HTMX swaps fire.
    var rail = document.getElementById('source-rail');
    if (rail) initialRailHTML = rail.innerHTML;

    wireSourceSheet();
    wireMoreSheet();
    wireFooterAccordion();
    wireMobileSearch();
    // Mirror the page's default rail into the sheet body so opening it via the
    // pill shows page-level provenance (matching what the rail would show on first paint).
    mirrorRailToSheet();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
