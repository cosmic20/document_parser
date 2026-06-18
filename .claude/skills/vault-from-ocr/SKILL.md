---
name: vault-from-ocr
description: >
  Build or update an Obsidian study-notes vault from document_parser output of typed or
  printed documents OCR'd with GOT-OCR2. Trigger when the user wants to turn printed/typed
  PDFs into a vault, mentions "vault", "obsidian", "study notes", or "notes from PDF", or
  provides document_parser JSON whose `metadata.model` is `got-ocr2`.
---

# Vault from OCR

Transform document_parser JSON produced from **typed / printed** documents (GOT-OCR2
backend) into a well-structured, cross-linked Obsidian vault.

Before anything else, read `.claude/skills/shared/vault-conventions.md` (relative to the repo
root) — it defines the concept-first model, folder layout, note format, linking rules, the concept
index, and merge-on-growth. This skill only adds the input-specific cleanup guidance below; for
multi-document batches, `vault-build` orchestrates this skill.

## Input-specific cleanup (typed/printed OCR / GOT-OCR2)

This JSON comes from `got-ocr2` reading typed or printed text, so cleanup is **MODERATE** —
far fewer garble artifacts than handwriting, but still needed:

- **Reconstruct tables and formulas into LaTeX** — GOT-OCR2 may flatten or mangle table
  and equation layout; rebuild them into clean tables and `$...$` / `$$...$$` LaTeX.
- **Trim OCR noise** — strip stray characters, broken line wraps, and header/footer cruft.
- **Fix obvious recognition errors** using subject-matter knowledge (e.g. confused
  characters, split or merged words).
- **Never hallucinate** content that isn't in the source.
- **Be thorough** — capture ALL content from every page; nothing dropped.

Pages with `source: text_layer` were extracted directly from a digital text layer and
need only a **light** touch.
