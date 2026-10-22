# Memory & Index — Imperal system extension

The user-facing window into **everything Webbee remembers about you**: the code
index it builds while working in your repos, the durable notes it distils from
those turns, and everything else it keeps in the Tenant Vault — working memory,
plans, conclusions, saved command outputs, conversations, the context graph.
See every detail as stored, correct the notes when Webbee learned something
wrong, and forget any part of it through one verified delete.

`app_id: memory-index` · v1.3.0 · system extension · capabilities `memory:read`, `memory:write`

---

## Why this exists

Webbee remembers your repos across machines, checkouts and surfaces (terminal,
panel, Telegram). That memory was previously invisible: you could not see what
it held, where it lived, when it refreshed, or fix a note that had gone stale.

This extension makes all of it inspectable and — for the notes — editable.

## What Webbee actually stores

Two kernel-written stores, kept together in **one Tenant Vault file per
repository** — `repos/<repo_key>` — and reached only through the auth gateway's
owner-scoped `/v1/memory` (the gateway takes no user id; it acts as you). This
extension keeps no state or cache of its own.

| Store | Where | Holds | Written by | Updates | Bounds |
|---|---|---|---|---|---|
| **Code index** | Tenant Vault, `repos/<repo_key>` | file/language counts, symbol kinds, key symbols with `file:line`, semantic-chunk count, test hints, endpoint/schema evidence, the exact commit indexed | the terminal coding agent, during indexing | rebuilt from the source tree on the next indexing pass | — |
| **Durable notes** | Tenant Vault, `repos/<repo_key>` (same file) | prose facts about the repo (conventions, architecture, gotchas) with file citations | the kernel distiller at the tail of a coding turn — **and by you**, through this extension | appended/merged per turn; your edits apply immediately | 40 notes per repo, 400 chars each, no expiry |

Your user & workspace facts and directives live in the vault's facts/law store;
deleting one removes its rule row for real (no tombstone).

### Everything else — and the one way to forget it

The index and notes are only part of it. For each repository the vault also
holds working memory (turn notes, files and commands seen, seen output lines),
goals and plan items with their evidence, proven conclusions, saved command
outputs, terminal conversations, session snapshots and context-graph events;
the account holds rules, conversations, conclusions, the reality matrix and
extension data. Memory of a repo whose code index was already deleted can
remain — it is shown as **"code index deleted — memory left over"**.

* **Shown as it is** — `GET /v1/memory/all` lists every place (`account`,
  `repo:<repo_key>`) with every non-zero count; this extension renders all of
  it ("Everything Webbee holds"), unknown sections under their raw name.
  Nothing is hidden and nothing is cleaned up automatically.
* **One forget door** — every delete (`delete_repo`, `forget_memory`, the
  panel's buttons) goes through the vault's forget (`POST /v1/memory/forget`,
  `DELETE /v1/memory/repo` for a repo), which takes every section at once,
  stops a running Webbee session on it first, and answers 409 naming what is
  left if it could not take everything.
* **Verified** — afterwards the whole memory is read again; success is reported
  only when the thing is gone, otherwise what is left is named.

A note save carries the version it was read at: if Webbee wrote in between, the
save is refused and you are asked to retry — your edit is never silently lost,
and it never silently overwrites a newer note.

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
* **Storage** (main) — the explainer: where each store lives, who writes it, when
  it updates, what the caps are — rendered with **live numbers from your own
  data**, not prose claims.
* **Everything Webbee holds** (main) — the whole memory: your account, every
  repo and the memory left from deleted repos, each count in plain words, each
  conversation and extension's data with a delete, and "Forget everything".
  Every delete asks for confirmation first.

## Chat tools

Reads — `list_repos`, `get_index`, `list_notes`, `explain_memory`,
`get_cross_repo_contract_graph`, `recall_context`, `list_user_facts`,
`memory_overview` (everything Webbee holds, place by place)
Writes — `add_note`, `edit_note`, `delete_note`, `add_user_fact`,
`edit_user_fact`, `delete_user_fact` (a real delete of the rule)
Destructive — `delete_repo` (erases everything of one repo, orphans included,
then verifies by re-reading the whole memory), `forget_memory` (one place,
conversation, rule, conclusion, reality matrix, extension's data, graph
subject, or everything — through the one forget door, then verified)

All work from every surface: panel chat, Telegram, and the terminal.

## Safety

Notes are re-injected into the coding brain's prompt on later turns, so every
write — including yours — goes through the same pipeline the kernel distiller
uses, in this order:

1. **Secret scrubbing** — API keys, bearer tokens, JWTs, connection-string
   credentials, AWS/GitHub/Slack/Stripe/GCP key shapes → `[REDACTED]`.
2. **Fence neutralisation** — newlines collapsed and `<<<` / `>>>` runs made
   inert, so stored text can never break out of its DATA frame and be read as an
   instruction (stored prompt-injection with no expiry otherwise).
3. **Clamp + LRU cap** — 400 chars per note, 40 notes per repo, oldest evicted.

Every call acts as the kernel-authoritative `ctx.user.imperal_id`, and the
gateway accepts no user id: you can only ever reach your own repositories. There is no cross-user surface, which
is why no admin scope is required.

Reads are **fail-soft**: if the vault is unreachable you get an honest
"nothing stored yet", never a broken turn. Writes are not: a note save that
fails is reported as an error.

## Development

```bash
python -m pytest tests/ -q
imperal build .                # regenerate imperal.json from the code
imperal validate .             # federal SDK rules (V1-V24+V31)
```

`imperal.json` is **generated** — edit the code, not the manifest, then rebuild.

---

© 2026 Imperal, Inc. Published through the
[Imperal Cloud Developer Portal](https://panel.imperal.io/developer).
