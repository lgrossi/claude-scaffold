# LSP

When a language server is active, prefer LSP over Grep/Glob for code navigation:

- Definitions, references, implementations, type info → LSP.
- Before renaming or changing a signature → `findReferences` first.
- Text/pattern searches (strings, config values, comments) → Grep/Glob.
