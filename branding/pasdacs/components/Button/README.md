# Button

The one control for actions and links, in five variants and three sizes.

- **primary** (`primary-fill` / `on-primary`): the main action on a screen, once per view. "Contact us", "Book a demo", "Approve".
- **secondary** (`accent-fill` / `on-accent`): a second mint action, sparingly.
- **outline** (`line-strong` border): the quieter alternative beside a primary ("Our services", "Send back").
- **ghost**: inline and toolbar actions.
- **inverse** (white with `brand-900` text and `shadow-glow` on hover): only on dark bands.

Sizes: `sm` (`btn-h-sm`, `btn-pad-sm`), `md` default (`btn-h-md`, `btn-pad-md`), `lg` (`btn-h-lg`, `btn-pad-lg`, `button-lg` text). Radius `radius-btn`.

The consumer provides the label (sentence case, a verb first) and an optional trailing arrow → that nudges 2px right on hover. States: hover lifts 1px, press scales to 0.98, focus shows a 2px `focus-ring` outline offset 2px, disabled is 50% opacity.
