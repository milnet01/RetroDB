---
name: Bug report
about: A reproducible bug — something is broken or behaves wrong
title: "Bug: "
labels: bug
assignees: ''
---

<!--
Thanks for taking the time to file a bug. RetroDB is solo-developed, so a
clear reproduction is the single biggest thing that decides whether a bug
gets fixed quickly.

Security issues should be reported privately — see SECURITY.md.
-->

## Environment

- **RetroDB version:** <!-- find this in Settings → About, or `config.py:APP_VERSION`. e.g. 3.6.14 -->
- **Install type:** <!-- source ZIP / standalone (PyInstaller) / git clone -->
- **OS:** <!-- Linux distro + version / Windows 10/11 / macOS version -->
- **Python version:** <!-- `python3 --version` — only for source/git-clone installs -->
- **Browser:** <!-- Chrome 142 / Firefox 128 / Safari 18 etc. — only for UI bugs -->

## What happened

<!-- One or two sentences. What were you doing, and what went wrong? -->

## Steps to reproduce

<!--
Step-by-step from a known starting state. The more concrete the better.
-->

1.
2.
3.

## Expected behaviour

<!-- What should have happened instead? -->

## Actual behaviour

<!-- What did happen? Include error messages verbatim. -->

## Log excerpt

<!--
RetroDB writes per-category logs under `logs/`. The most useful ones for
a bug report are usually:
  - logs/app.log         (server-side errors, request traces)
  - logs/scraper.log     (scraper / API issues)
  - logs/job.log         (background job issues)

Paste the relevant 20–50 lines around the failure inside the block below.
The log redactor strips API keys / tokens before write, so the file is
generally safe to share — but skim it first.
-->

```
(paste log excerpt here)
```

## Screenshot / video (optional)

<!-- Drag-and-drop into the issue body. Helpful for visual bugs. -->

## Anything else

<!-- Workarounds you've tried, related issues, hunches about what's wrong. -->
