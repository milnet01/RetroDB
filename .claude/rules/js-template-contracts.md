---
paths:
  - "templates/**"
  - "static/js/**"
---

## Non-Obvious JS / Template Contracts

Use these names exactly in template `<script>` blocks — never invent aliases.
Globals are defined in `static/js/utils.js`, `main.js`, `toast-controller.js`,
`game-modals.js`, `theme.js`, and `templates/base.html` (the two dialog
primitives `showConfirm` / `showModal` live in `base.html` rather than a JS
file so the CSP-nonce script-tag inlines them). Read source for full
signatures.

- **Events (CSP)**: no inline `onclick=` / `onchange=` etc. — the enforcing CSP blocks them. Write `data-on-click="fn"` (any bubbling event: `click`, `change`, `input`, `keydown`, `keyup`, `keypress`, `submit`, `mouseover`, `mouseout`) with `data-args='[...]'` (JSON; `"$this"`, `"$event"`, `"$this.value"`, `"$this.dataset.x"`), plus `data-stop`, `data-prevent`, `data-self-only`, `data-key="Enter"`, `data-clear-value` as needed. In HTML a script builds, `data-args="${actionArgs(a, '$this')}"`. `fn` is a dotted path from `window`: a page `const` or a function in a bundled file needs `window.fn = fn`. Image fallbacks use `data-on-error`. Both live in `main.js`; `tests/test_fu1_csp.py` pins them.
- **Toasts/dialogs**: `showNotification(msg, type, duration?)` (`utils.js`), `showConfirm(title, msg, onConfirm, opts?)` (`base.html`), `showModal(title, msg, onConfirm?, showCancel?, onCancel?)` (`base.html`).
- **HTTP/storage**: `API.get/post/postForm`, `Storage.get/set/remove/clearAll`.
- **Utilities**: `escapeHtml`, `formatNumber` (thin-space thousands), `formatBytes`, `copyToClipboard`, `debounce`, `throttle`, `DOM.$/$$/create/toggle/delegate`, `DateUtils`.
- **Game modals**: `GameDetailModal.open/close/clearCache`, `GameEditModal.open/save/close`, `HLTBManager.lookup/save/cancel/clear`, `triggerAiFill`.
- **Sticky nav**: `StickyScroll.to(target)`, `.stackPositions()`, `.updateMargins()`. Mark sticky elements containing anchor links with `data-sticky-nav`. Both `stackPositions()` + `updateMargins()` run on DOMContentLoaded in `main.js`; call them again after tab/panel switches that show/hide sticky navs. Code that sets a sticky bar's `top` itself adds `StickyScroll.baseTop()`, the phone header's height where it shows (PASS-59-165).
- **Themed icons**: `getThemedIcon(key, fallback?)` (defined in `static/js/toast-controller.js`) returns icons matching the current theme (e.g. `'error'` → `❌` on cyberpunk, `✗` on matrix). Keys: job types (`bulk-scrape`, `ra-sync`, `ra-refresh`...), job states (`paused`, `resume`, `complete`, `queued`, `cancelled`, `background`), notifications (`success`, `error`, `warning`, `info`), stats (`stat-success`, `stat-failed`, `stat-skipped`), actions (`starting`, `running`, `cancel`, `save`, `loading`). `background` is a state, not an action — matches the bucketing in `toast-controller.js` and `docs/specs/themes.md` §7. In HTML use `data-themed-icon="key"` — `main.js` auto-populates on DOMContentLoaded.
- **A11y**: `ModalFocusTrap.activate(modalEl, triggerEl, {onEscape, autoFocus})` / `.deactivate()` — WCAG 2.4.3, stacks for nested modals, restores focus to trigger on close.
- **Number formatting**: Jinja `{{ value|format_number }}`; JS `formatNumber(value)`.
- **Server controls** (`main.js`): `restartServer()` (`POST /api/restart`, `os.execv` re-exec) and `shutdownServer()` (`POST /api/shutdown`, admin-only graceful stop — a delayed thread sends `SIGTERM` to the drain handler in `app.py`; shutdownServer does NOT poll to reconnect). Both exported on `RetroDB`/`window`; buttons in `_settings_tabs/system.html` Server Controls card.

Themes (display name on left, `internal key` in backticks): Cyberpunk (`cyberpunk`, default), Matrix (`matrix`), Amber (`amber`), Ocean (`ocean`), Cathedral (`christian`), Blade Runner (`bladerunner`), Elite (`elite`).
