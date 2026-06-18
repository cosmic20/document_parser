This file holds the shared conventions read by all `vault-from-*` skills. It defines the source-agnostic guidance for turning document_parser JSON into a well-structured Obsidian vault: the linking hierarchy, note format, MOC structure, workflow, and folder layout. The individual `vault-from-*` skills carry only their own OCR/cleanup specifics and defer to this document for everything else.

# Vault Conventions

Build and maintain an Obsidian vault from document_parser JSON output. New content is
split into topic-focused notes, cleaned up, and cross-linked to existing vault knowledge.

## Linking Philosophy

The vault follows a **directed knowledge hierarchy** to keep links tractable:

**Foundational subjects** (math, probability, linear algebra, statistics) are the base
layer. They define concepts but do NOT link upward to their applications.

**Applied subjects** (machine learning, computer vision, optimization, NLP, robotics, etc.)
link DOWN to foundational concepts they use, but foundational notes are not updated to
link back.

This means links flow in one direction: **applied → foundational**. A computer vision note
on RANSAC can link to [[Binomial Distribution]] or [[Concentration Inequalities]], but
those probability notes should NOT be updated to mention RANSAC. This prevents circular
links and keeps foundational notes clean and stable.

**Within the same layer**, notes link freely to each other (a CV note can link to another
CV note, a probability note can link to another probability note).

### How to classify a subject

- **Foundational**: probability, statistics, linear algebra, calculus, real analysis,
  abstract algebra, discrete math, information theory, measure theory
- **Applied**: machine learning, computer vision, NLP, robotics, optimization,
  signal processing, control theory, graphical models, deep learning

When unsure, ask: "Does this subject define tools that other fields use?" If yes,
it's foundational. If it consumes tools from other fields, it's applied.

### Link sparingly

Only link when a concept is **meaningfully used**, not just name-dropped. If a note
mentions "probability" in passing, don't link it. If it derives a formula using Bayes'
theorem, link [[Bayes' Theorem]].

A good test: would a reader benefit from jumping to that note to understand
the current material? If not, skip the link.

## Workflow

### 1. Gather inputs

Ask the user for:
- **Source**: path to the document_parser JSON file (or directory of JSON files)
- **Vault path**: where to write/update the Obsidian vault

If the user provides a raw PDF instead of JSON, tell them to run document_parser first:
```
uv run docparse parse <pdf_path> --output <output_dir>
```

### 2. Index the existing vault

Before writing anything, read the vault to understand what's already there:

1. List all `.md` files in the vault
2. For each note, read its **frontmatter** (tags, course, topic) and **first few headings**
3. Build a mental index: what concepts exist, what subject area each belongs to, what
   links already exist

This index is critical — it tells you what to link to and prevents duplicate notes.

### 3. Read and analyze the new content

Load the document_parser JSON. The structure is:
```json
{
  "filename": "Gradient Descent.pdf",
  "pages": [
    {
      "page": 1,
      "text": "raw OCR or text-layer content",
      "source": "qwen-vl-3b | got-ocr2 | text_layer",
      "images": [{"id": "p1_img0", "width": 800, "height": 600, "path": "..."}]
    }
  ],
  "metadata": { ... }
}
```

Read ALL pages and identify:
- What subject area is this? (foundational or applied?)
- What are the distinct topics/concepts?
- Where do natural topic boundaries fall?
- What existing vault notes does this content reference or depend on?

### 4. Plan the notes

Decide the note structure before writing anything:
- One note per major topic/concept
- Determine which existing notes each new note should link to
- Respect the linking hierarchy: if this is applied content, identify foundational
  concepts to link down to. If foundational, only link within the same layer.

### 5. Write each note

For each topic, write a `.md` file using the Write tool.

#### Note format

```markdown
---
tags:
  - topic-tag
  - subtopic-tag
source: "Original PDF filename"
course: "Course number and name (if applicable)"
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
> Statement in clean LaTeX.

> [!definition] Definition Name
> Precise definition.

> [!example] Example
> Worked example or illustration.

> [!note]
> Additional context or intuition.

## Related

- [[Other Note In Same Subject]]
- [[Foundational Concept Used Here]]
```

#### Formatting rules

- **Title**: filename IS the title. Do NOT start the body with `# Title`.
- **Math**: `$...$` inline, `$$...$$` display. Use proper LaTeX commands.
- **Callouts**: `[!theorem]`, `[!definition]`, `[!lemma]`, `[!proof]`, `[!example]`, `[!note]`, `[!warning]`
- **Tags**: lowercase kebab-case. Include subject area and specific topics.
- **Images**: embed with `![[images/p1_img0.png]]` if referenced in parsed data.

### 6. Update the Map of Content

Each subject area should have its own MOC. Create or update the relevant one:

```markdown
---
tags:
  - MOC
course: "Course number (if applicable)"
---

## Topics

- [[Note Name]] — one-line summary
- ...

## Sources

- filename.pdf (N pages, handwritten/typed)
```

If the vault has multiple subject areas, consider a top-level `MOC.md` that links
to each subject's MOC.

### 7. Verify

After writing all notes, read back 1-2 to check:
- LaTeX delimiters are balanced
- Internal links use exact filenames of existing notes
- YAML frontmatter is valid
- Content is complete — nothing dropped

## Multi-PDF workflow

When processing additional PDFs into an existing vault:
1. Index existing notes first (step 2)
2. Identify overlapping topics — update existing notes rather than creating duplicates
3. Add cross-links respecting the hierarchy (applied → foundational only)
4. Append new sources to the relevant MOC

## Folder structure

Organize by subject area, one level deep:
```
Vault/
├── MOC.md                    (top-level index)
├── 21-325 Probability/
│   ├── MOC - Probability.md
│   ├── Bayes' Theorem.md
│   └── ...
├── 16-385 Computer Vision/
│   ├── MOC - Computer Vision.md
│   ├── RANSAC.md
│   └── ...
└── images/
```

Don't nest deeper than one folder. Obsidian resolves `[[links]]` by filename
regardless of folder, so flat-within-folder works well.
