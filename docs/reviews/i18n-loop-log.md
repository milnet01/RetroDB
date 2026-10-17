# i18n spec — cold-eyes loop log

Review history for `docs/specs/i18n.md`. Rows start with the PASS-59-94 amendment (pseudolocale admin-only); earlier passes of the spec carried no loop log.

## Cold-eyes loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-10-17 | 2 (neutral-lane; every lane held every question) | 0 | 2 | 0 | 0 | Gated span: the PASS-59-94 amendment to §3 (last paragraph), §5 (Admins only paragraph) and §8 (first paragraph). 2 distinct findings, 1 verified / 1 dismissed, 1 fixed. Both lanes independently reported (Q2): §5 said `Accept-Language: eo` selects the pseudolocale "for anyone, signed in or not", but §3's branch 1 answers first for every signed-in user, because `locale_preference` defaults to `'en'` (reproduced: saved `'en'` with `Accept-Language: eo` selects `en`; an SQLite `ADD COLUMN ... DEFAULT 'en'` fills existing rows). Fixed by narrowing the sentence to callers the earlier branches do not answer. Dismissed (one lane, Q2): §8's "user-pref beats all" pin and "All locale assertions read `PSEUDO_LOCALE`" against the new branch-1 rule; the test can set an admin caller or use a real locale, a local detail, and no passage contradicts another. Open questions resolved clean: 3 (rows with a NULL preference: none, the default fills them; `has_permission` reading `g.user` outside `load_user`: implementer-local; a non-admin's stored `eo` in the narrowed dropdown: implementer-local). 1b yield: every citation windowed, none defective. Lanes disclosed only the global CLAUDE.md and the MCP banner; no git snapshot. Lane b was re-dispatched alone after its first launch never started; both lanes read the same frozen subject. Loop 2 dispatched. |
