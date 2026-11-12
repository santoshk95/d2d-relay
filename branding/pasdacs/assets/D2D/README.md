# D2D

The D2D mark and lockups. D2D (Data to Decision) is the dashboard builder in the Relay Platform by PASDACS, so its mark sits in the PASDACS tile: the same rounded ink tile, white glyph and one mint element. They are new and not on pasdacs.com.

The mark is a D cut into five rows of data. The middle row is the decision, in the logo mint `#00C48C`: the one row that matters, and the brand's sign for proven.

- `d2d-lockup.svg`: mark + D2D + DATA TO DECISION, for light grounds. Ink tile and D2D in `#111111`, DATA TO DECISION in `#525252`.
- `d2d-lockup-dark.svg`: for dark grounds. White tile with ink rows, D2D in white, DATA TO DECISION in `#A3A3A3`.
- `d2d-mark.svg`: the mark alone, 48×48, for light grounds. `d2d-mark-dark.svg` is the white tile for dark grounds.
- `d2d-favicon-mark.svg`: three heavier rows for 16 to 47 px (browser tabs, app icons), as `favicon-mark.svg` is for PASDACS.
- `d2d-mark.png`: 512×512 mark on a transparent ground, for app icons, structured data and slides.
- `d2d-lockup.png`: 720×192 transparent lockup, for email signatures and documents.
- `d2d-share.html`: the source of D2D Relay's 1200x630 share image (`webapp/static/og/d2d-relay.png`, what LinkedIn,
  WhatsApp, Facebook and X show for a d2d.pasdacs.com link): the sign-in page's dark band, the dark lockup, its
  headline and line, and the mint bar. To redraw it, open the file in Chromium at 1200 x 630 and take a screenshot
  (or with Playwright, as item 38 did), then replace the PNG.

## Construction

Everything is drawn in the 48 box the PASDACS mark uses.

- Tile: 44×44 at (2, 2), corner radius 11 (`radius-mark`).
- The D: x 13.5 to 35.5, y 13 to 35. Its bowl is a half circle of radius 11 centred at (24.5, 24); the two outer left corners round at 1.6.
- Rows: five, 3.28 high with 1.4 gaps. The favicon mark has three, 6.07 high with 1.9 gaps. The middle row is mint in both.
- Lockup: set like the RELAY lockup. D2D in Manrope 800, 23 px, tracked +3, from x 60; DATA TO DECISION in Manrope 700, 9.5 px, tracked +2, from x 61. The file is 180 wide.

## Rules

- The middle row is always `#00C48C`. The other rows and the tile only swap between ink and white to suit the ground.
- Keep clear space of at least half the tile around the mark.
- Below 48 px use `d2d-favicon-mark.svg`, and never show the mark under 16 px.
- Never stretch it, add effects, or set it on a busy image.
- In sentences write D2D. Spelled out it is "D2D, Data to Decision", a Relay Platform product by PASDACS.

The SVG lockups are live text in Manrope. Where Manrope is not installed, outline the text before sending the file to print or a third party, or use the PNG.
