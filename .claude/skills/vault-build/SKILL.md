---
name: vault-build
description: >
  Integrate a whole batch of processed class documents into the single concept-first Obsidian
  vault. Trigger when the user wants to build/update their vault from a folder or batch (mentions
  "vault", "build the vault", "integrate my classes/notes", or points at a class folder's
  `batch_index.json` / `_parsed/` output). This skill orchestrates the per-source `vault-from-*`
  skills across many documents.
---

# Vault Build (batch integrator)

Drive a batch of processed documents into the **one** long-lived, concept-first Obsidian vault.
This skill does NOT reimplement note-writing — it **orchestrates** the three input skills
(`vault-from-marker`, `vault-from-ocr`, `vault-from-handwriting`) and enforces the vault model.

Before anything else, read `.claude/skills/shared/vault-conventions.md` — it defines the concept
model, folder layout, note format, linking rules, the concept index, and merge-on-growth. This
skill only adds the batch orchestration below.

## Inputs
- One or more **class folders** that have been processed by `docparse batch run`, each containing
  `_parsed/batch_index.json` (documents with `status: processed`) and `_parsed/<stem>/<stem>.json`.
- The **vault path** (a dedicated standalone folder, e.g. `~/CMU-Vault/`). Confirm it with the user
  if unknown; it is remembered in `~/.docparse.toml`.

## Critical constraint: single serial integrator
The vault is one mutable tree. **Integrate documents strictly one at a time, in order — never
spawn parallel agents to write into the vault.** Concurrent writers would race on the same
canonical notes and MOCs and corrupt dedup. (Document *processing* in Part A can run in parallel;
*integration* here cannot.)

## Procedure
1. **Index the vault**: run `uv run docparse vault index --vault <path>` and load
   `<vault>/.vault-index.json` (concepts, aliases, topics, `topic_edges`). This is your dedup +
   link-resolution + cycle-check map. Re-run it after each document (step 6).
2. **Collect work**: read each class folder's `_parsed/batch_index.json`; take documents with
   `status: processed` (skip `integrated`). **Within each class, integrate them in the curated
   order** — lecture 1 first, then on through the last:
   - **Order authority = the class's `batch.toml` manifest, if present.** Its `[[documents]]` order
     is what the user arranged (e.g. by dragging rows in the web app), so iterate documents in that
     exact order and use `batch_index.json` only to look up each one's `status`/`json_path` (join on
     `file`). The web app keeps `batch_index.json` in this same order too, so a freshly written index
     already reflects it.
   - **No manifest? Infer from the names.** Parse a lecture/week number from each document's `file`
     stem / `title` (e.g. `lecture01`, `lec-1`, `L3`, `week05b`, `Lecture 12`, `04b`) — leading
     number plus any `a`/`b` part suffix — and sort ascending; documents with no parseable number
     keep their index order and sort last.

   Curated order is preferred over inference because the user may name lectures by content rather
   than number. Either way this mirrors teaching order, so foundational concepts are created before
   the applied ones that build on them — fewer dangling links and cleaner first-pass merges.
   Correctness does **not** depend on the order (see Notes / "Order independence"); across
   *different* classes the order is free.
3. For each document:
   1. Load its `json_path`. Pick the input skill by `metadata.model`:
      `marker → vault-from-marker`, `got-ocr2 → vault-from-ocr`,
      `qwen-vl-3b`/`qwen-vl-7b` → `vault-from-handwriting`. Apply that skill's cleanup stance.
   2. Determine the **provenance string** from the index entry: `"<course> — <title>"`. This is
      what you append to each touched note's `sources`.
   3. Identify the distinct **concepts** in the document.
   4. For each concept, look it up in the vault index (by title or alias):
      - **New** → create the canonical note in its **native subject** folder (create the folder and
        its `MOC - <Topic>.md` if missing); embed images into that folder's `images/`.
      - **Exists** → open it and **merge additively** (new sections, reconciled overlaps, conflicts
        flagged), appending the provenance to `sources` and any new `aliases`.
   5. Add links **sparingly**, applied → foundational, running the cross-topic **cycle-check**
      against `topic_edges` before each cross-topic link (drop + flag anything that would reverse an
      existing dependency). Forward references to not-yet-created concepts stay as dangling links.
   6. Update the topic MOC and the top-level `MOC.md`.
   7. Mark the document `integrated` in its `batch_index.json`, then **re-index** the vault so the
      next document sees the new notes/links.
4. **Report**: notes created vs merged, dangling links left, any flagged cross-topic conflicts or
   rejected cycle links.

## Notes
- **Order independence**: integrate classes in whatever order the user gives — see the conventions'
  "Processing order does not matter". Don't ask them to process foundational courses first.
- **Idempotency**: a document already `integrated` is skipped; re-running merges nothing twice
  because `sources` already lists it.
- **Don't dedup by folder** — a concept is one note across all courses; always check aliases.
