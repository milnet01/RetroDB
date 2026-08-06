<!--
Thanks for the PR! A short, well-framed description gets it merged faster.
Match the project's commit-message contract:
  - title is a single line, imperative voice, ~70 chars max
  - body explains the WHY first, then the WHAT
-->

## What

<!--
1–3 sentences. What does this change actually do? Skip restating the
title; the diff covers the WHAT in detail.
-->

## Why

<!--
The motivation: what bug, what feature request, what user pain. If
this fixes an issue, link it (`Fixes #123`).
-->

## How

<!--
Outline of the approach, only when it's not obvious from the diff.
Mention any non-obvious trade-offs or things you considered and
rejected. Skip otherwise.
-->

## Mandatory-workflow checklist

<!-- See `CLAUDE.md` § Mandatory Workflow. Tick what applies. -->

- [ ] **Version bumped** in `config.py` + `config.example.py` (`APP_VERSION` + `APP_LAST_UPDATE`)
- [ ] **Changelog entry** added at the top of `data/changelog.yaml`
- [ ] **CSS rebuilt** (`python3 build_css.py`) — if any `static/css/**.css` changed
- [ ] **JS rebuilt** (`python3 build_js.py`) — if any bundled `static/js/*.js` changed
- [ ] **Tests run** (`python3 -m pytest`) — if `services/*.py` or `scraper/*.py` changed
- [ ] **Lockfile regenerated** (`uv pip compile … --generate-hashes`) — if `requirements.txt` changed
- [ ] **CLAUDE.md updated** — if routes / templates / bundled JS / CSS files / page-asset wiring changed

## Verification

<!--
What did you actually test? Be concrete — "ran pytest" vs "walked the
edit-game flow at desktop + mobile, confirmed the new field saves and
re-renders after a reload, dev-tools console clean". UI changes should
state what was clicked and what was observed.
-->

## Screenshots (UI changes only)

<!--
Before / after if the visual changed. Drag-and-drop into the PR body.
-->
