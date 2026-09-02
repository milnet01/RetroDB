#!/usr/bin/env bash
#
# release-standalone.sh — cut a GitHub *draft* release for the current RetroDB
# version with self-contained standalone bundles for Linux + Windows (+ macOS).
#
# WHY this needs CI (and a script): PyInstaller cannot cross-compile, so a
# Windows standalone can only be built on a real Windows machine. RetroDB's
# .github/workflows/release.yml has a `build-standalone` matrix
# (ubuntu / macos / windows-latest) that builds each one natively, but it is
# gated behind a manual workflow_dispatch with build_standalone=true (the
# bundles are ~600 MB each, so it is opt-in). This script automates the whole
# dance: tag the release, trigger that workflow, wait for it, and tidy the
# draft's release notes.
#
# SAFETY: the release is left as a DRAFT. Nothing is made public by this
# script — review the assets on the Releases page and click "Publish" (or run
# `gh release edit vX.Y.Z --draft=false`) yourself.
#
# Requires: git, gh (authenticated; `repo` + `workflow` scopes), python3 with
# PyYAML (only for copying the changelog into the release notes — skipped if
# unavailable).
#
# Usage:
#   ./release-standalone.sh                 # version auto-detected from config
#   ./release-standalone.sh --version 3.10.0

set -euo pipefail
cd "$(dirname "$0")"

WORKFLOW="release.yml"
REMOTE="origin"
BRANCH="main"

say() { printf '%s\n' "$*"; }
die() { printf '\xe2\x9c\x96 %s\n' "$*" >&2; exit 1; }

# ── Resolve version → tag ────────────────────────────────────────────────────
VERSION=""
[[ "${1:-}" == "--version" ]] && VERSION="${2:-}"
if [[ -z "$VERSION" ]]; then
  # config.example.py is the tracked source of truth the CI build uses
  # (release.yml does `cp config.example.py config.py`); config.py is gitignored.
  VERSION="$(grep -oP 'APP_VERSION\s*=\s*"\K[0-9][^"]*' config.example.py | head -1)"
fi
[[ -n "$VERSION" ]] || die "Could not determine version (pass --version X.Y.Z)."
TAG="v$VERSION"
say "▶ Releasing $TAG  (standalone Linux + Windows)"

# ── Preflight ────────────────────────────────────────────────────────────────
command -v git >/dev/null || die "git not found."
command -v gh  >/dev/null || die "gh CLI not found (https://cli.github.com)."
gh auth status >/dev/null 2>&1 || die "gh not authenticated — run: gh auth login"

git fetch --quiet "$REMOTE" "$BRANCH"
git merge-base --is-ancestor HEAD "$REMOTE/$BRANCH" \
  || die "HEAD isn't pushed to $REMOTE/$BRANCH — push your commits first so the tag points at a commit the runners can check out."

# Refuse to clobber an already-published release; a leftover draft is fine to reuse.
if [[ "$(gh release view "$TAG" --json isDraft -q .isDraft 2>/dev/null || true)" == "false" ]]; then
  die "$TAG is already a PUBLISHED release. Bump the version before re-releasing."
fi

# ── Tag (triggers the source-ZIP job; we cancel that to avoid racing) ─────────
if git ls-remote --tags --exit-code "$REMOTE" "refs/tags/$TAG" >/dev/null 2>&1; then
  say "• Tag $TAG already on $REMOTE — reusing it."
else
  say "• Creating + pushing tag $TAG"
  # Pass 59.18 — a local $TAG left over from an earlier attempt makes `git tag`
  # fail, and the `|| true` swallowed it; the push then published the OLD
  # commit's tag and the whole matrix built the wrong tree while this script
  # reported success. The preflight above only proves HEAD is on the remote
  # branch, and the ls-remote check above misses a tag that never got pushed.
  if existing="$(git rev-parse -q --verify "refs/tags/$TAG^{commit}")"; then
    [[ "$existing" == "$(git rev-parse HEAD)" ]] \
      || die "Local tag $TAG points at $existing, not HEAD. Delete it (git tag -d $TAG) or check out the right commit."
    say "  reusing existing local tag $TAG (already at HEAD)"
  else
    git tag -a "$TAG" -m "RetroDB $TAG"
  fi
  git push "$REMOTE" "$TAG"
  # Pushing a tag auto-triggers release.yml (on: push: tags) — the source-ZIP
  # job only. We immediately run the SAME workflow via workflow_dispatch (which
  # builds the source ZIPs *and* the standalones), so the push-triggered run is
  # redundant. Cancel it (best-effort) so two runs don't race on one draft.
  say "• Cancelling the redundant push-triggered run…"
  for _ in $(seq 1 12); do
    rid="$(gh run list -w "$WORKFLOW" -e push -L 8 \
            --json databaseId,headBranch,status \
            -q "[.[] | select(.headBranch==\"$TAG\" and .status!=\"completed\")][0].databaseId" 2>/dev/null || true)"
    if [[ -n "${rid:-}" ]]; then gh run cancel "$rid" >/dev/null 2>&1 && say "  cancelled run $rid"; break; fi
    sleep 5
  done
fi

# ── Dispatch the standalone build ────────────────────────────────────────────
# Record the most-recent EXISTING workflow_dispatch run id BEFORE dispatching, so
# we can tell the run we're about to create apart from a stale prior dispatch.
# Without this, `gh run list -L 1` returns an OLD completed dispatch in the window
# before GitHub registers the new run — the watcher then "completes" instantly
# against the wrong run and the release is never finalised (the 2026-06-30 bug).
prev_rid="$(gh run list -w "$WORKFLOW" -e workflow_dispatch -L 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
say "• Dispatching $WORKFLOW (build_standalone=true)"
gh workflow run "$WORKFLOW" -f tag="$TAG" -f build_standalone=true

# Poll until a NEW workflow_dispatch run (id != prev_rid) appears.
rid=""
for _ in $(seq 1 24); do
  cand="$(gh run list -w "$WORKFLOW" -e workflow_dispatch -L 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
  if [[ -n "$cand" && "$cand" != "$prev_rid" ]]; then rid="$cand"; break; fi
  sleep 5
done
[[ -n "$rid" ]] || die "Couldn't find the dispatched run (none newer than ${prev_rid:-none}) — check the Actions tab."
say "• Watching run $rid — the 3-OS standalone matrix takes ~15-30 min…"
gh run watch "$rid" --exit-status \
  || die "Release run failed. Inspect with: gh run view $rid --log-failed"

# ── Tidy the draft's release notes ───────────────────────────────────────────
# On a manual workflow_dispatch the workflow's changelog-extraction step reads
# the branch ref, not the tag, so it leaves a placeholder body. Set the notes
# from data/changelog.yaml ourselves. Best-effort — skipped if python/yaml absent.
if command -v python3 >/dev/null; then
  notes="$(python3 - "$VERSION" <<'PY' 2>/dev/null || true
import sys
try:
    import yaml
except ImportError:
    sys.exit(0)
ver = sys.argv[1]
for e in yaml.safe_load(open('data/changelog.yaml')) or []:
    if str(e.get('version')) == ver:
        print((e.get('body') or '').strip())
        break
PY
)"
  if [[ -n "${notes:-}" ]]; then
    tmp="$(mktemp)"; printf '%s\n' "$notes" > "$tmp"
    gh release edit "$TAG" --notes-file "$tmp" >/dev/null && say "• Release notes set from changelog."
    rm -f "$tmp"
  fi
fi

# ── Report (draft only — never auto-published) ───────────────────────────────
say ""
say "✔ Draft release ready: $(gh release view "$TAG" --json url -q .url)"
say "  Standalone bundles you asked for:"
gh release view "$TAG" --json assets -q '.assets[].name' \
  | grep -E 'Standalone\.zip$' | grep -Ei 'linux|windows' | sed 's/^/    • /' \
  || say "    (none found — check the run logs; the matrix may still be uploading)"
say ""
say "  All release assets:"
gh release view "$TAG" --json assets -q '.assets[].name' | sed 's/^/    /'
say ""
say "  This is a DRAFT. Review it, then publish when ready:"
say "    gh release edit $TAG --draft=false      # or click Publish in the web UI"
say "  (macOS is also built by the CI matrix — ignore it if you don't need it.)"
