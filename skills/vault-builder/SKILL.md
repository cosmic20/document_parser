---
name: vault-builder
description: >
  Transform document_parser JSON output into a well-structured Obsidian vault.
  Use whenever the user wants to build or update an Obsidian vault from parsed PDFs,
  create study notes from lecture content, organize OCR output into topic-based notes,
  or mentions "vault", "obsidian", "notes from PDF", "study notes", or "build notes".
  Also trigger when the user provides a document_parser JSON file and wants it turned
  into usable notes. Works with both handwritten and typed PDF content.
---

# Vault Builder

Build and maintain an Obsidian vault from document_parser JSON output. Each parsed PDF
becomes a set of topic-focused notes with proper LaTeX math, internal links, callouts,
and a Map of Content.

## Workflow

### 1. Gather inputs

Ask the user for:
- **Source**: path to the document_parser JSON file (or a directory of JSON files)
- **Vault path**: where to write the Obsidian vault (create if it doesn't exist)

If the user provides a raw PDF instead of JSON, tell them to run document_parser first:
```
uv run docparse parse <pdf_path> --output <output_dir>
```

### 2. Read the parsed JSON

Use the Read tool to load the JSON file. The structure is:
```json
{
  "filename": "Gradient Descent.pdf",
  "pages": [
    {
      "page": 1,
      "text": "raw OCR or text-layer content",
      "source": "qwen-vl-3b | got-ocr2 | text_layer",
      "images": [{"id": "p1_img0", "width": 800, "height": 600, "path": "images/p1_img0.png"}]
    }
  ],
  "metadata": { ... }
}
```

### 3. Analyze and plan topics

Read ALL pages and identify distinct topics/concepts. Think about:
- What are the major concepts covered?
- Where do natural topic boundaries fall?
- Which concepts deserve their own note vs. being a section within a larger note?

Aim for **one note per major topic**. A 5-page PDF on gradient descent might produce:
- Gradient Descent (overview, motivation, update rule)
- Convergence Rates (linear, superlinear, sublinear, quadratic)
- Gradient Descent on Smooth Functions (descent lemma, convergence bounds)
- Gradient Descent on Strongly Convex Functions (condition number, linear convergence)
- MOC (Map of Content linking everything)

### 4. Check existing vault

Read the vault directory to see what notes already exist. If there are related notes,
plan to add `[[internal links]]` to them from the new notes (and vice versa — update
existing notes to link back).

### 5. Write each note

For each topic, write a `.md` file to the vault directory using the Write tool.

#### Note template

Every note MUST follow this structure:

```markdown
---
tags:
  - topic-tag
  - subtopic-tag
source: "Original PDF filename"
date: YYYY-MM-DD
---

## Overview

Brief summary of what this note covers.

## Section Heading

Content with inline math $f(x) = x^2$ and display math:

$$
\nabla f(x^{(k)}) = A x^{(k)} - b
$$

> [!theorem] Theorem Name
> Precise statement in clean LaTeX.
> $$\|x^{(k)} - x^*\|_2 \leq \left(\frac{\kappa - 1}{\kappa + 1}\right)^k \|x^{(0)} - x^*\|_2$$

> [!definition] Definition Name
> Precise definition.

> [!example] Example
> Worked example or illustration.

> [!note]
> Additional context, intuition, or caveats.

## Related

- [[Other Note Name]]
- [[Another Related Concept]]
```

#### Formatting rules

**Title**: The filename IS the title. Do NOT start the note body with `# Title`.

**Math**: Use `$...$` for inline and `$$...$$` for display blocks. Use proper LaTeX
commands: `\nabla`, `\leq`, `\|`, `\mathbb{R}`, `\in`, `\forall`, `\exists`,
`\frac{a}{b}`, `x^{(k)}`, `\sum`, `\lim`, `\inf`, `\sup`, etc.

**Callouts**: Use Obsidian callout syntax for theorems, definitions, lemmas, proofs,
examples, and notes. Available types: `[!theorem]`, `[!definition]`, `[!lemma]`,
`[!proof]`, `[!example]`, `[!note]`, `[!warning]`, `[!tip]`.

**Internal links**: Use `[[Note Name]]` liberally. If a concept is mentioned that has
its own note, link it. If it SHOULD have its own note, still link it — Obsidian shows
unresolved links which helps identify gaps.

**Images**: If the parsed data includes images, embed with `![[images/p1_img0.png]]`.
Copy images into the vault's `images/` subfolder if they aren't already there.

**Tags**: Use lowercase kebab-case. Include the subject area and specific topics.
Example: `optimization`, `convex-analysis`, `gradient-descent`.

### 6. OCR cleanup

The parsed text contains OCR errors. You MUST clean these up:

- Fix garbled words (e.g., "60al" → "Goal", "vegetate gradient" → "negative gradient")
- Reconstruct math from broken OCR into proper LaTeX
- Use subject-matter knowledge to infer what garbled expressions should be
- Strip repetition artifacts (repeated words/tokens from OCR model failures)
- Mark genuinely unreadable content as `[unclear]` — do NOT hallucinate content
- Preserve ALL content from the source — be thorough, don't skip hard parts

### 7. Create/update Map of Content

Write or update `MOC.md` at the vault root:

```markdown
---
tags:
  - MOC
---

## Topics

- [[Gradient Descent]] — overview, motivation, update rule
- [[Convergence Rates]] — linear, superlinear, quadratic rates
- ...

## Sources

- Gradient Descent.pdf (5 pages, handwritten)
- ...
```

### 8. Verify

After writing all notes, read back 1-2 of them to verify:
- LaTeX renders correctly (no broken delimiters)
- Internal links use exact note filenames
- Frontmatter YAML is valid
- Content is complete — nothing dropped from the source

## Multi-PDF workflow

When processing multiple PDFs into the same vault:
1. Read existing MOC.md and vault notes first
2. Identify overlapping topics — update existing notes rather than creating duplicates
3. Add new links between old and new content
4. Append new sources to MOC.md

## Important

- **Be thorough**: capture ALL content from every page. Don't skip pages or sections.
- **Quality over speed**: take time to properly reconstruct math from OCR artifacts.
- **Link aggressively**: the value of an Obsidian vault is in its connections.
- **One concept per note**: split into focused notes rather than one giant dump.
- **Study-ready**: write notes that would genuinely help someone study this material.
