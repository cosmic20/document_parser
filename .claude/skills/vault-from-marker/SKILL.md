---
name: vault-from-marker
description: >
  Build or update an Obsidian study-notes vault from document_parser output produced by the
  MARKER parser. Trigger when the user wants to turn marker-parsed documents into a vault,
  mentions "vault", "obsidian", "study notes", or "marker", or provides document_parser JSON
  whose `metadata.model` is `marker`.
---

# Vault from Marker

Transform document_parser JSON produced by the **marker** parser into a well-structured,
cross-linked Obsidian vault.

Before anything else, read `.claude/skills/shared/vault-conventions.md` (relative to the repo
root) — it defines the concept-first model, folder layout, note format, linking rules, the concept
index, and merge-on-growth. This skill only adds the input-specific guidance below; for
multi-document batches, `vault-build` orchestrates this skill.

## Input-specific schema (marker)

Marker output differs from the OCR/handwriting skills: it ships **structured blocks**, not
just flat text. Each page object has the usual `page`, `text`, `source` (== `"marker"`),
and `images` fields, PLUS:

- **`blocks`** — a list of structured block dicts, each
  `{"id", "block_type", "bbox", "html"}`. `block_type` is one of marker's types such as
  `SectionHeader`, `Text`, `Table`, `Equation`, `TextInlineMath`, `Figure`, `ListItem`,
  `PageHeader`, `PageFooter`, `Handwriting`, etc. The `html` is **fully-resolved HTML** for
  that block — tables arrive as `<table>...</table>`, equations as math/LaTeX-bearing HTML,
  headings as `<h1>`/`<h2>`, lists as `<ul>`/`<ol>`, and so on. This is the primary signal.
- **`markdown`** — may be present per page, but is often `null`/absent in the current
  implementation. Rely primarily on `blocks`; use `markdown` when present.
- **`text`** — a flattened plain-text version (tags stripped). Usable as a fallback, but it
  loses table and equation structure, so prefer `blocks`.

## Input-specific cleanup (marker)

Marker has ALREADY done layout analysis, reading order, table structure, and equation
recognition, so cleanup is **MINIMAL** compared to the OCR skills. The job here is mostly
**translation + organization**, not reconstruction:

- **Translate each block's HTML into clean Obsidian markdown**: `<table>` → Markdown
  tables, equation HTML / math → `$...$` or `$$...$$` LaTeX, `<h1>`/`<h2>` → markdown
  headings (but remember the note title IS the filename — see shared conventions, don't
  start the body with `# Title`), `<ul>`/`<ol>` → markdown lists.
- **Preserve marker's structure and content VERBATIM** where possible. Do NOT re-derive or
  hallucinate content — marker's extraction is trusted.
- **Drop `PageHeader` / `PageFooter` blocks** (running heads, page numbers) as noise.
- **Let `block_type` drive callouts** where appropriate — e.g. an `Equation` block →
  display math `$$...$$`; a definition-like `Text` block → `[!definition]` only if it is
  clearly one. Don't force callouts onto plain prose.
- **Split the page stream into topic-focused notes** per the shared conventions; embed
  images via the saved `images` refs (`![[images/p1_img0.png]]`).
- **Treat `Handwriting` blocks with a bit more skepticism** (they were handwritten) but
  still trust marker's read.
