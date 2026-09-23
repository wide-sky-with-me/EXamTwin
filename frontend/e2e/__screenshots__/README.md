# Diagram visual references

Playwright routes references through `{platform}/{arg}{ext}`. The two PNGs directly
in this directory are retained as legacy references; their rendering environment
was not recorded. Do not assume they represent a particular operating system.

## Linux reference environment

- Browser: installed Google Chrome, headless, `151.0.7922.173`.
- Browser platform: `Linux x86_64`; locale `zh-CN`; light color scheme.
- Viewports: desktop 1280 × 720; narrow screen 390 × 844.
- The application system-font stack resolves the desktop title/caption to
  Liberation Sans (verified with Chrome DevTools `CSS.getPlatformFontsForNode`).
  Mathematical labels use the bundled KaTeX webfonts.
- Fixture: `e2e/fixtures/diagram.html`, using the real `AnswerDiagramView` and
  application styles, without test-only CSS or font overrides.

Platform separation avoids treating every system-font stack as pixel-identical.
It does not pin the Chrome version or the installed fonts; a future rendering
change must still be inspected rather than accepted automatically.

## Review of the Linux desktop reference

The previous desktop reference was 1280 × 599; the current capture is 1280 × 597.
The current figure measures 596.27 CSS pixels high; its plot stage is 720 × 458.80
at x=280, y=66. Differences are in text rendering, legend/caption vertical metrics,
and the card/toolbar surface: the old image is white, whereas the fixture now
uses the existing light-theme `--surface: #fbfcfe`. The source of the old image
is insufficient to attribute every difference exclusively to the operating system.

The plot itself was checked independently: RGB pixels in rectangles
`(330,160)–(850,420)`, `(330,290)–(950,430)`, and `(400,200)–(800,400)` were
identical between old and current desktop captures (135,200 / 86,800 / 80,000
pixels respectively). These overlapping regions cover the curves, shaded region,
and major grid/axis geometry. All six KaTeX labels and all four controls remain
visible; the mobile case still exercises zoom to 125% and fullscreen expansion.

No application styles, assertions, or screenshot tolerances were changed for
these references. Legacy PNGs are not overwritten.

## Validation

From `frontend/`, with the project development server available:

```sh
PLAYWRIGHT_PORT=4175 pnpm test:visual
```

Use a free local port appropriate for the machine. New platform references must
be visually reviewed and generated explicitly; ordinary validation must run
without `--update-snapshots`.
