---
name: vault-from-handwriting
description: >
  Build or update an Obsidian study-notes vault from document_parser output of
  HANDWRITTEN notes (Qwen-VL vision backends). Trigger when the user wants to turn
  handwritten lecture notes into a vault, mentions "vault", "obsidian", "handwritten
  notes", or "study notes", or provides document_parser JSON whose `metadata.model`
  is `qwen-vl-3b` or `qwen-vl-7b`.
---

# Vault from Handwriting

Transform document_parser JSON produced from **handwritten** notes into a well-structured,
cross-linked Obsidian vault.

Before anything else, read `skills/shared/vault-conventions.md` (relative to the repo
root) — it defines the linking hierarchy, note format, MOC structure, and folder layout
used here. This skill only adds the input-specific cleanup guidance below.

## Input-specific cleanup (handwriting / Qwen-VL)

This JSON comes from a vision-LLM (`qwen-vl-3b` / `qwen-vl-7b`) reading messy handwriting,
so cleanup is **HEAVY**:

- **Fix garbled words** using subject-matter knowledge — the model frequently misreads
  handwritten characters, so reconstruct the intended word from context.
- **Reconstruct math into proper LaTeX** — handwritten equations are often mangled;
  rebuild them into clean `$...$` / `$$...$$` LaTeX.
- **Strip repetition / loop artifacts** — vision OCR can get stuck repeating words or
  phrases on hard pages; remove these.
- **Mark genuinely unreadable content** as `[unclear]`.
- **Never hallucinate** content that isn't in the source.
- **Be thorough** — capture ALL content from every page; nothing dropped.

Pages with `source: text_layer` were extracted directly from a digital text layer (not
vision OCR) and need only **light** cleanup.
