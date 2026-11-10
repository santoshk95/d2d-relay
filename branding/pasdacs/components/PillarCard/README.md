# PillarCard

A card for one pillar or module: the big letter, a Lucide icon, a title and one line.

Cards never float alone: put them in one grid frame (`radius-card`, 1px `line` border) with 1px `line` gaps between cells, each cell on `surface` with `card-pad`. The letter is `pillar-letter` in `accent-text`; the icon is 20px in `ink-subtle`, turning `accent-text` on hover; the title is `card-title` in `ink`; the line is `small` in `ink-muted`. On hover the site adds a pointer-following mint spotlight (10% `accent-500`).

The consumer provides the letter (or a short code), the icon name, the title, one sentence and the link. In Relay the same card can show a module with a status word ("Live", "Coming soon") in `accent-text` or `ink-subtle`.
