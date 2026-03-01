---
paths:
  - "**/*.md"
  - "**/*.rst"
  - "**/*.adoc"
  - "**/*.asciidoc"
---

# Markup Language

## Semantic Line Breaks (Sembr)

Follow semantic line break conventions per https://sembr.org/ for all lightweight markup languages (Markdown, AsciiDoc, reStructuredText, etc.).

**Core principle:** Add line breaks after substantial units of thought, not at arbitrary character limits.

### Rules

**Line break placement:**
- After sentences (terminal punctuation: `.` `!` `?`)
- After independent clauses (marked by `;` `:` `—`)
- Never after commas — comma breaks fragment naturally flowing prose
- Before lists
- Optionally after dependent clauses for grammatical clarity
- Optionally before/after hyperlinks and inline markup

**Never break:**
- Within hyphenated words
- In ways that alter rendered output

**Line length:**
- Soft limit: 80 characters (break at semantic boundaries before hitting this)
- Exceptions: URLs, code blocks, tables (don't break these)

### Benefits

- **Source mirrors thought structure** — easier to write and reason about
- **Easier editing** — grammatical units are isolated, changes produce clean diffs
- **Invisible to readers** — rendered output unchanged (markup joins consecutive lines with spaces)

### Example

**Bad (arbitrary line wrapping):**
```markdown
All human beings are born free and equal in dignity and rights. They are
endowed with reason and conscience and should act towards one another in a
spirit of brotherhood.
```

**Good (semantic breaks):**
```markdown
All human beings are born free and equal in dignity and rights.
They are endowed with reason and conscience
and should act towards one another in a spirit of brotherhood.
```

### Anti-Patterns

- Breaking mid-sentence at 80 characters regardless of meaning
- Using trailing spaces for breaks (use `<br/>` elements when hard breaks are needed)
- Breaking within inline code, URLs, or hyphenated-words
