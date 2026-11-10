# SectionHeading

The heading block that opens every section: an optional eyebrow, a title and an optional lede.

- Eyebrow: `eyebrow` style in `accent-text` (on a dark band, `accent-400`). Two to four words, a category not a sentence.
- Title: `section-title` in `ink` (white on a dark band). Sentence case, no full stop.
- Lede: `lede` in `ink-muted` (`brand-100` on a dark band), one or two sentences, max width 48rem.

The consumer provides the three strings, the alignment (left by default, centred for a closing call to action) and whether it sits on a dark band. Leave `heading-gap` below it before the content.
