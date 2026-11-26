# Green & Mint theme kit

Light and dark theme from the Scheme Compliance Assistant POC.

| File | What it is |
|---|---|
| `demo.html` | Open it in a browser to see the theme. Use the Light / Dark / System switch at the bottom left. |
| `theme.css` | All colour, weight and shape tokens for both themes. |
| `components.css` | Sidebar, page header, cards, buttons, inputs, tables, badges and links. |
| `head-snippet.html` | Paste into `<head>` before your stylesheets, so the right theme shows on first paint. |
| `theme.js` | Light / Dark / System switch controller (ES module). |
| `THEME_GUIDE.md` | Full guide: every token, component recipe, contrast ratios and rules. |

## Use it in your project

1. Copy `theme.css` and `components.css` into your project and load them, `theme.css` first.
2. Paste `head-snippet.html` into your page's `<head>`, above the stylesheets.
3. Import `theme.js`, call `initTheme()` once on start-up, and call `setPreference('light' | 'dark' | 'system')` from your switch buttons.
4. Build components with the `--ds-*` tokens. Don't hard-code colours or font weights.
