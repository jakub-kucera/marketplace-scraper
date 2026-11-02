# Copilot Instructions for `marketplace-scrapper`

The authoritative guide for this repository is [`CLAUDE.md`](../CLAUDE.md) at the repo root -
commands, architecture, coding patterns, testing conventions and the committing/writing-style
rules all live there. Read it before making a change.

This file previously duplicated a (now very stale) summary of that document. Keeping one
source of truth avoids the two drifting apart again - which is what happened here: the `bazos`
app has since been renamed to `marketplace`, `SendableMixin` was replaced by a `Sendable`
Protocol, the blacklist pre-flight probe this file still mentioned was deleted, and the test
suite it called "minimal" now has thousands of tests.
