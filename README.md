# Memory & Index — Imperal system extension

The user-facing window into **Webbee's per-repository brain**: the code index it
builds while working in your repos, and the durable notes it distils from those
turns. See every detail, understand exactly where each piece lives and when it
updates — and correct the notes when Webbee learned something wrong.

`app_id: memory-index` · system extension · capabilities `memory:read`, `memory:write`

---

## Why this exists

Webbee remembers your repos across machines, checkouts and surfaces (terminal,
panel, Telegram). That memory was previously invisible: you could not see what
it held, where it lived, when it refreshed, or fix a note that had gone stale.

This extension makes all of it inspectable and — for the notes — editable.

## What Webbee actually stores

Two kernel-owned Redis stores, one pair per repository:

| Store | Key | Holds | Written by | Updates | Bounds |
|---|---|---|---|---|---|
| **Code index** | `imperal:repo_index_map:{your_id}:{repo_key}` | file/language counts, symbol kinds, key symbols with `file:line`, semantic-chunk count, test hints, endpoint/schema evidence, the exact commit indexed | the terminal coding agent, during indexing | rebuilt from the source tree on the next indexing pass | — |
| **Durable notes** | `imperal:repo_memory:{your_id}:{repo_key}` | prose facts about the repo (conventions, architecture, gotchas) with file citations | the kernel distiller at the tail of a coding turn — **and by you**, through this extension | appended/merged per turn; your edits apply immediately | 40 notes per repo, 400 chars each, 90-day TTL refreshed on every write |

`repo_key` is a stable hash of the repository's git origin URL (falling back to
its absolute path). Same origin ⇒ same key ⇒ the same memory from any checkout,
worktree or machine. A repo with **no** git origin gets keyed by path, so
different checkouts of it hold *separate* memory — the `explain_memory` tool
and the Storage panel both point this out when it applies to you.

## Why the index is read-only here

The index is regenerated deterministically from your actual source tree. A hand
edit would be silently overwritten on the next indexing pass, so offering an
edit control would promise something the platform discards. Notes are different:
they are prose judgements, and you know better than a distiller LLM whether one
is still true.

## Panels

* **Repositories** (sidebar) — inventory: every repo, its file count, note count,
  index freshness, and whether semantic search is ready.
* **Memory** (main) — one repo in full: the code index, then every note with
  edit/delete controls, plus an add-note form.
* **Storage** (main) — the explainer: which key holds what, who writes it, when
  it updates, what the caps are — rendered with **live numbers from your own
  data**, not prose claims.

## Chat tools

Reads — `list_repos`, `get_index`, `list_notes`, `explain_memory`
Writes — `add_note`, `edit_note`, `delete_note`

All work from every surface: panel chat, Telegram, and the terminal.

## Safety

Notes are re-injected into the coding brain's prompt on later turns, so every
write — including yours — goes through the same pipeline the kernel distiller
uses, in this order:

1. **Secret scrubbing** — API keys, bearer tokens, JWTs, connection-string
   credentials, AWS/GitHub/Slack/Stripe/GCP key shapes → `[REDACTED]`.
2. **Fence neutralisation** — newlines collapsed and `<<<` / `>>>` runs made
   inert, so stored text can never break out of its DATA frame and be read as an
   instruction (stored prompt-injection with a 90-day shelf life otherwise).
3. **Clamp + LRU cap** — 400 chars per note, 40 notes per repo, oldest evicted.

Every key is derived from the kernel-authoritative `ctx.user.imperal_id`: you
can only ever reach your own repositories. There is no cross-user surface, which
is why no admin scope is required.

Reads are **fail-soft**: if Redis is unavailable you get an honest "nothing
stored yet", never a broken turn.

## Development

```bash
python -m pytest tests/ -q     # 19 tests
imperal build .                # regenerate imperal.json from the code
imperal validate .             # federal SDK rules (V1-V24+V31)
```

`imperal.json` is **generated** — edit the code, not the manifest, then rebuild.

---

© 2026 Imperal, Inc. Published through the
[Imperal Cloud Developer Portal](https://panel.imperal.io/developer).
