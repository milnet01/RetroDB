<!-- ants-spec-format: 1 -->
# PASS-59-332 — Play sessions, and a status for each person

**Status:** built (2026-11-25).
**Kind:** feature.
**Source:** ROADMAP PASS-59-332 (user request 2026-11-23; scope answers
2026-11-25).

Layman: each person in the house has their own Not Started / In Progress /
Completed status for every game. When you really play a game from RetroDB,
it moves your status to In Progress and remembers how long you played.

## 1. Goal

Every game started with the Play button records a session for the person who
pressed it: when it started and how long it ran. A session that shows real
play moves that person's status from Not Started to In Progress. The status
itself belongs to each person, not to the game.

## 2. Problem

1. `games.completion_status` is one column for everyone. A status one person
   sets changes every account's library, so `routes/games.py::api_update_completion`
   also demands the `edit` permission, and its docstring waits for "the
   per-user move".
2. Nothing records a Play-button session. `platform_play_time` holds only what
   Steam reports (`services/jobs/platform_sync.py::_save_steam_play_time`).
3. Session ends are seen late. `services/launcher/local.py::LocalLauncher._mark_exited`
   runs when something polls (`active()`, `status()`, `kill()`), so its
   `exit_time` is the time of the poll, and `on_exit` is set only for the
   built-in player (`services/launch_resolver.py::_player_context`).
4. The launch knows its user only inside the request
   (`launch_resolver._launching_user_id`); `LaunchContext` has no `user_id`.

## 3. Scope decisions (agreed with the user)

- **Each person has their own status** (user, 2026-11-25), not one shared
  status moved by play. This reaches the Library cards, the game page, bulk
  edit, the dashboard, Analytics and the collector trophies.
- **Existing statuses go to the first admin only** (user, 2026-11-25). Every
  other account starts with every game Not Started.
- **Save changes are checked only for the built-in player** (user,
  2026-11-25). The user's own RetroArch and standalone emulators count an
  earned achievement, else get the one-click question. Their save folders are
  §9.
- **The rule** (user, 2026-11-23, roadmap body): at least 10 minutes AND (a
  save file changed OR a RetroAchievement was earned) moves Not Started to In
  Progress. A long session with neither asks once, with one click. It never
  touches Played, Completed, 100% or a status the person set by hand.
- Author's choices: "asks once" is once per person per game; a status set
  from the game page, the edit modal or bulk edit counts as set by hand, even
  when it is Not Started.

## 4. Design

### 4.1 Tables (migration 048)

```sql
CREATE TABLE user_game_status (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id    INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    status     TEXT NOT NULL,          -- one of VALID_COMPLETION_STATUSES
    set_by     TEXT NOT NULL,          -- 'hand' | 'play'
    asked      INTEGER NOT NULL DEFAULT 0,  -- 1 once the question was shown
    ask_pending INTEGER NOT NULL DEFAULT 0, -- 1 while it waits for an answer
    updated_at TEXT,
    PRIMARY KEY (user_id, game_id)
);
CREATE TABLE play_sessions (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    emulator_id INTEGER,
    started_at  INTEGER NOT NULL,      -- epoch seconds
    seconds     INTEGER NOT NULL,
    save_changed INTEGER NOT NULL DEFAULT 0,
    achievement  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_play_sessions_user_game ON play_sessions(user_id, game_id);
```

The migration copies every `games.completion_status` that is set and not
`not_started` into `user_game_status` for `_helpers._admin_user_id`, with
`set_by = 'hand'`. No admin → nothing is copied. `games.completion_status`
stays as a column nothing writes, as `games.last_viewed` did after migration
010.

A missing row means Not Started, not set by hand.

### 4.2 The status, per person

`services/game_status.py` (new) owns both tables:

```python
def status_for(user_id, game_id) -> str
def set_by_hand(user_id, game_ids, status) -> None
def record_session(user_id, game_id, emulator_id, started_at, seconds,
                   save_changed, achievement) -> str | None   # 'moved' | 'ask' | None
def answer(user_id, game_id, yes: bool) -> None
def play_seconds(user_id, game_id) -> int
```

Readers change to the current user's row, through a `LEFT JOIN
user_game_status ugs ON ugs.game_id = g.id AND ugs.user_id = ?` returning
`COALESCE(ugs.status, 'not_started') AS completion_status`, so
`game_metadata_service._CARD_COLUMNS` and the JavaScript keep their key:

- `services/game_query.py` list query and `routes/games.py` card-data query.
- `routes/games.py::api_game_detail` and `game_detail`.
- `app.py::get_stats` (`completed_games`) and the continue-playing panel.
- `services/analytics.py::_get_analytics_stats`, with the user id in the
  analytics cache key, so one person never sees another's numbers.
- `routes/collector_trophies.py` `completed_count`.

Writers: `api_update_completion` calls `set_by_hand` for the current user
and loses `@permission_required('edit')`; `track_progress` stays. Bulk edit
takes `completion_status` out of its shared `UPDATE games` and calls
`set_by_hand` for the editing user.

### 4.3 Sessions

- `LaunchContext` and the registry entry gain `user_id`, set in
  `routes/launch.py::_launch_game` from `g.user['id']`, and `save_check`.
- `LocalLauncher._drain_stderr` already runs one daemon thread per launch.
  After stderr closes, for a launch with a `user_id`, it calls `proc.wait()`,
  takes `time.time()` as the end, and calls
  `services/play_sessions.py::session_ended(entry, ended_at)`. This runs for
  every kind of launch, polled or not. `on_exit` and its timing
  (PASS-59-64 "When the hook runs") are unchanged.
- **Save change, built-in player only.** At launch,
  `launch_resolver._player_context` sets `save_check` to
  `player.save_watch(rom)`, which records the modification time of each file
  under `<profile>/saves` and `<profile>/states` named after the ROM.
  `session_ended` calls it. A new file or a later time is a change.
- **Achievement.** Where the game has `ra_game_id` and the user has RA
  credentials in their `user_settings`, `session_ended` asks
  `scraper.retroachievements.get_user_game_progress_custom` once and counts
  any `date_earned` or `date_earned_hardcore` inside the session, or up to
  two minutes after it. The code reads RA's times as UTC; RA's API
  documentation does not state their zone. Under 10 minutes it does not ask.
- `record_session` writes the session, then applies §3's rule: 10 minutes or
  more, status Not Started and not set by hand → `save_changed or
  achievement` moves it to In Progress with `set_by = 'play'`; otherwise, if
  never asked, it sets `ask_pending`.

### 4.4 The question, and play time

- While `ask_pending` is set, the game page shows one line under the status
  dropdown: "You played this for N min. Mark it In Progress?" with Yes and No.
  Either answer calls `POST /api/game/<id>/play-question` → `answer()`, which
  clears `ask_pending` and sets `asked`. Yes also sets In Progress, `set_by =
  'hand'`.
- After a Play from the game page, `static/js/game-launch.js` asks
  `GET /api/game/<id>/play-question` each time the window gets focus back,
  and shows the same line without a reload. The launch-status poll cannot
  carry it: the Play screen stops polling after 15 seconds.
- The game page shows "Played in RetroDB: X h Y min" beside the Steam line,
  from `play_seconds`.

## 5. Invariants

- **INV-1** — One person's status never changes another's: setting it by
  hand, in bulk or by play writes only that person's row.
  *Test:* `tests/test_pass59_332_play_sessions.py::test_status_is_per_person`.
  *Breaks when:* any writer still updates `games.completion_status`, or a
  reader drops the `user_id` condition.
- **INV-2** — The migration gives the first admin every set status and gives
  other accounts none.
  *Test:* `tests/test_pass59_332_play_sessions.py::test_migration_copies_to_admin_only`.
  *Breaks when:* rows are copied for every user, or `not_started` rows are copied.
- **INV-3** — Play moves only Not Started that was not set by hand, and only
  to In Progress.
  *Test:* `tests/test_pass59_332_play_sessions.py::test_play_moves_only_untouched_not_started`
  — fixtures: a 20-minute session with a save change against each other
  status, and against a hand-set Not Started.
  *Breaks when:* the `set_by` check or the status check is missing.
- **INV-4** — A session under 10 minutes never moves a status and never asks,
  even with a save change.
  *Test:* same file, `test_short_session_changes_nothing` (9 min 59 s, save
  changed).
  *Breaks when:* the length check is missing or uses the poll time.
- **INV-5** — A long session with neither a save change nor an achievement
  asks once per person per game, and never again after an answer.
  *Test:* same file, `test_question_is_asked_once`.
  *Breaks when:* `asked` is not set, or is checked per session.
- **INV-6** — A session's length is the process's own run, not the time of a
  poll: with nothing polling, a session is still recorded when the emulator
  exits.
  *Test:* `tests/test_pass59_332_play_sessions.py::test_session_recorded_without_polling`
  — a launch of a short-lived process, no `status()`/`active()` call.
  *Breaks when:* recording hangs off `_mark_exited`.
- **INV-7** — The analytics numbers are the asking person's.
  *Test:* same file, `test_analytics_is_per_person` (two users, cache warm
  for the first).
  *Breaks when:* the cache key lacks the user id.
- **INV-8** — A failure in session recording (RA unreachable, database busy)
  never stops the launcher or the player's `on_exit`; the session is logged
  and skipped.
  *Test:* same file, `test_recording_failure_is_contained`.
  *Breaks when:* `session_ended` raises out of the drain thread.

## 6. Failure modes

- RetroDB stops while a game runs: the daemon thread dies, and that session
  is not recorded. Accepted; nothing else is lost.
- RetroAchievements does not answer: the achievement is counted as not
  earned, so the session falls to the save check or the question.
- A Flatpak or a launcher script that forks and exits early: the session
  ends when the parent exits, so it may be short and move nothing. The same
  is true of `on_exit` today.
- No `g.user` at launch is impossible: `api_launch_game` is `@login_required`.

## 7. Tests

`tests/test_pass59_332_play_sessions.py` holds INV-1 to INV-8. Each is seen
red against the code before the change. Existing tests that pin the shared
status change with it: `tests/test_pass59_63_routes.py::test_viewer_sets_only_their_own_completion`
replaces the old 403 test, and
`tests/test_services_review_fixes.py`'s analytics test gains a user.

## 8. Alternatives considered (and rejected)

- **One shared status moved by play** (offered 2026-11-25): smaller, but the
  user chose a status per person.
- **Copy existing statuses to every account** (offered 2026-11-25): the user
  chose admin only.
- **Sessions in `platform_play_time` with source `retrodb`**: it holds one
  total per source, not sessions, so the 10-minute rule and "asked once"
  would have nothing to read.
- **A new waiter thread per launch**: the stderr drain thread already exists
  per launch and ends with the process.

## 9. Out of scope

- Save-change checks for the user's own RetroArch and standalone emulators —
  deferred; not yet queued.
- Moving a status to Played or Completed automatically.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_pass59_332_play_sessions.py::test_status_is_per_person` |
| INV-2 | `tests/test_pass59_332_play_sessions.py::test_migration_copies_to_admin_only` |
| INV-3 | `tests/test_pass59_332_play_sessions.py::test_play_moves_only_untouched_not_started` |
| INV-4 | `tests/test_pass59_332_play_sessions.py::test_short_session_changes_nothing` |
| INV-5 | `tests/test_pass59_332_play_sessions.py::test_question_is_asked_once` |
| INV-6 | `tests/test_pass59_332_play_sessions.py::test_session_recorded_without_polling` |
| INV-7 | `tests/test_pass59_332_play_sessions.py::test_analytics_is_per_person` |
| INV-8 | `tests/test_pass59_332_play_sessions.py::test_recording_failure_is_contained` |
| The question's wording and placement | **nothing** — seen in the browser |

## 11. Cross-doc impact

- `CLAUDE.md` Schema / data shapes: a line on `user_game_status` and
  `play_sessions`.
- `docs/specs/PASS-59-64-launcher.md`: `LaunchContext` gains `user_id`; the
  drain thread records the session end.
- `docs/specs/auth.md`: `track_progress` alone sets a person's own status.
- `docs/specs/migrations.md`: migration 048.
- `data/changelog.yaml` and the locale changelogs; `templates/help.html` and
  its locale copies where they describe the status.

## 12. Cold-eyes loop log

Rows live in `../reviews/PASS-59-332-play-sessions-loop-log.md`.

## 14. Migration / compatibility

Migration 048 is additive: two new tables and a copy. `games.completion_status`
keeps its values, so a downgrade still shows the old shared statuses.
