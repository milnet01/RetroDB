#!/usr/bin/env bash
#
# hook-on-static-asset-edit.sh — PostToolUse hook for RetroDB.
#
# When Claude edits a static CSS or JS source file, surface a reminder
# that the production-bundled / minified assets need a rebuild before
# the change is live in the browser. We don't auto-run the build itself
# (~ a few seconds per pass and could mask compile errors during rapid
# iteration); instead we hint the right command in a systemMessage so
# the model sees it and can run the build at a sensible checkpoint.
#
# Wired in via .claude/settings.json:
#     PostToolUse → matcher Edit|Write → command bash <this script>
#
# Stdin: PostToolUse JSON. Short-circuit unless touched file is under
# static/css/ or static/js/.
# Stdout: nothing on non-relevant edits, or {systemMessage:"…"} naming
# the rebuild command.
# Exit: always 0.

set -u

PROJECT_ROOT="/mnt/Storage/Scripts/Linux/RetroDB"

file=$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)
case "$file" in
    "$PROJECT_ROOT"/static/css/*|*/static/css/*)
        cmd="python3 build_css.py"
        kind="CSS"
        ;;
    "$PROJECT_ROOT"/static/js/*|*/static/js/*)
        cmd="python3 build_js.py"
        kind="JS"
        ;;
    *)
        exit 0
        ;;
esac

# Only emit the reminder once per session per asset type — track via a
# tmpfile keyed on the session_id (PostToolUse JSON includes it). This
# stops the hint from spamming on every save during a CSS-tweak run.
session_id=$(jq -r '.session_id // "no-session"' 2>/dev/null)
sentinel="/tmp/retrodb-rebuild-hint-${session_id}-${kind}"
if [ -f "$sentinel" ]; then
    exit 0
fi
touch "$sentinel"

jq -n --arg cmd "$cmd" --arg kind "$kind" --arg file "$file" \
    '{systemMessage: ("ℹ RetroDB " + $kind + " source edited (" + $file + "). Run `" + $cmd + "` before testing in the browser. (This reminder shows once per session per asset type.)")}'
exit 0
