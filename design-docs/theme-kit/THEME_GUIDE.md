# Green & Mint theme guide (light and dark)

This guide describes the light and dark theme used by the Scheme Compliance Assistant POC, so other teams can build pages that look the same.

All colour values below were read from the running app, so they are the values that actually appear on screen. They aren't copied from a design file.

- **Section 9** has a self-contained starter (CSS + JS) that you can copy into a new project.
- **Section 10** lists where everything lives in this POC's code.

---

## 1. Design in one paragraph

- **Frame:** a dark forest-green sidebar on the left, the same in both themes.
- **Light mode:** a white page with white cards. Every main card has a 3px dark-green top border, the same green as the sidebar.
- **Dark mode:** a deep green-black page with dark green cards. Text is white or neutral grey, never green-tinted, and is set one weight bolder for readability.
- **Accent:** one green family, used for fills, borders, dots, icons and selection. It is never used for body text on a green background.

## 2. How theme switching works

| Item | Behaviour |
|---|---|
| Choices | **Light**, **Dark**, **System**. System is the default. |
| Where the choice is stored | `localStorage["ds-theme"]` holds `light` or `dark`. Choosing System removes the key. |
| How the theme is applied | The resolved theme is always written to `<html data-theme="light|dark">`. All CSS keys off this attribute. |
| No flash of the wrong theme | A tiny inline script in `<head>` sets `data-theme` before the first paint (see §9.3). |
| System mode | Follows `prefers-color-scheme` and updates live when the OS setting changes. |
| During the swap | The class `ds-theme-switching` on `<html>` disables transitions for two frames, so every component changes at once. |
| Other tabs | A change made in one tab is picked up by other open tabs through the `storage` event. |

## 3. Colour tokens

Use these semantic tokens and never raw hex in components. Values are given as Light / Dark.

### 3.1 Surfaces

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ds-bg-canvas` | `#FFFFFF` | `#07160F` | Page background |
| `--ds-bg-surface` | `#FFFFFF` | `#0B2119` | Cards, panels |
| `--ds-bg-raised` | `#F7FFF9` | `#0F2A20` | Raised areas, secondary buttons (dark) |
| `--ds-bg-sunken` | `#EEF8F2` | `#04100B` | Wells, code blocks |
| `--ds-bg-input` | `#FFFFFF` | `#04100B` | Form fields |
| `--ds-bg-hover` | `rgba(201,240,219,.50)` | `rgba(45,212,191,.06)` | Row / item hover |
| `--ds-bg-selected` | `#C9F0DB` | `rgba(45,212,191,.14)` | Selected row / list item |
| `--ds-bg-selected-hover` | `#C4EED7` | `rgba(45,212,191,.18)` | Selected + hover |
| `--ds-bg-pressed` | `#A3E0BF` | `rgba(45,212,191,.12)` | Mouse-down |
| `--ds-bg-neutral-tint` | `#EEF3F1` | `rgba(201,240,219,.06)` | Neutral badges, count chips |
| `--ds-bg-disabled` | `#E3ECE8` | `#18342A` | Disabled controls |
| `--ds-bg-tooltip` | `#052D22` | `#1A4033` | Tooltips (text `#FFFFFF`) |
| `--ds-bg-topbar` | `rgba(255,255,255,.92)` | `rgba(7,22,15,.90)` | Sticky mobile top bar |
| Table header (`--ds-warm-header`) | `#E9FFF4` | `#0F2A20` | `<th>` background |
| `--ds-table-body` | `#FFFFFF` | `transparent` | `<td>` background |
| `--ds-table-row-hover` | `rgba(201,240,219,.35)` | `rgba(45,212,191,.06)` | Table row hover |

### 3.2 Text

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ds-text-primary` | `#0F2C25` | `#FFFFFF` | Headings, body, numbers |
| `--ds-text-secondary` | `#4D6B5F` | `#D2D8D5` | Descriptions, meta |
| `--ds-text-tertiary` | `#4D6B5F` | `#AEB6B2` | Hints, placeholders |
| `--ds-text-disabled` | `#8AA39A` | `#9AA39F` | Disabled labels |
| `--ds-text-accent` | `#0B6E45` | `#FFFFFF` | Links, "All findings"-style actions |
| `--ds-on-fill-strong` | `#FFFFFF` | `#FFFFFF` | Text on primary buttons |

> **Dark-mode rule:** no green or teal text on green surfaces. Links in dark mode are white and underline on hover.

### 3.3 Accent and fills

| Token | Light | Dark | Use |
|---|---|---|---|
| `--ds-fill-strong` | `#0F7F50` | `#0F7F50` | Primary button fill |
| `--ds-fill-strong-hover` | `#0B6E45` | `#0B6E45` | Primary button hover |
| `--ds-fill-strong-active` | `#0B3D2E` | `#0B5E3B` | Primary button pressed |
| `--ds-accent` | `#0F7F50` | `#2DD4BF` | Checkboxes, spinners, tab underline |
| `--ds-accent-indicator` | `#16AB6D` | `#2DD4BF` | Selection bars, status dots, progress |
| `--ds-accent-subtle` | `#C9F0DB` | `rgba(45,212,191,.14)` | Accent tints (date chip, pills) |
| `--ds-accent-border` | `rgba(22,171,109,.40)` | `rgba(45,212,191,.30)` | Accent outlines |
| `--ds-focus-ring` | `#0F7F50` | `#2DD4BF` | 2px focus outline, 2px offset |

### 3.4 Borders

| Token | Light | Dark |
|---|---|---|
| `--ds-border-subtle` | `rgba(11,61,46,.08)` | `#17362B` |
| `--ds-border-default` | `rgba(11,61,46,.10)` | `#1F4336` |
| `--ds-border-strong` | `rgba(11,61,46,.18)` | `#2A5546` |
| `--ds-border-input` | `rgba(11,61,46,.55)` | `#4D7A69` |
| `--ds-border-input-hover` | `#0B3D2E` | `#6A9886` |
| `--ds-card-top-width` | `3px` | `1px` |
| `--ds-card-top-color` | `#0B3D2E` | `#1F4336` |

### 3.5 Sidebar ("shell")

The sidebar is dark green in both themes.

| Token | Light | Dark |
|---|---|---|
| `--ds-shell-bg` | `#0B3D2E` | `#082A20` |
| `--ds-shell-active-bg` | `#052D22` | `#041A13` |
| `--ds-shell-hover` | `rgba(201,240,219,.08)` | `rgba(201,240,219,.07)` |
| `--ds-shell-text` | `#C9F0DB` | `#F2F5F4` |
| `--ds-shell-text-hi` (active item) | `#FFFFFF` | `#FFFFFF` |
| `--ds-shell-label` (section labels) | `#9FBDB1` | `#B4BDB9` |
| `--ds-shell-border` | `rgba(201,240,219,.08)` | `rgba(201,240,219,.08)` |
| Active indicator bar, icons | `#2DD4BF` | `#2DD4BF` |
| Brand tile | `#2DD4BF` bg / `#0B3D2E` text | `#0F7F50` bg / `#FFFFFF` text |
| Count pill (e.g. Reviews 14) | `#2DD4BF` bg / `#052D22` text | `#0F7F50` bg / `#FFFFFF` text |

### 3.6 Status colours

| Status | Text (L / D) | Tint (L / D) | Border (L / D) | Solid |
|---|---|---|---|---|
| Success | `#0B6E45` / `#FFFFFF`* | `#C9F0DB` / `rgba(95,211,154,.12)` | `#16AB6D` / `rgba(95,211,154,.30)` | `#16AB6D` |
| Info | `#0E6F78` / `#FFFFFF`* | `#E6FBF8` / `rgba(108,200,214,.12)` | `#2DD4BF` / `rgba(108,200,214,.30)` | `#0E9384` |
| Warning | `#B54708` / `#F2B25C` | `#FFFAEB` / `rgba(242,178,92,.12)` | `#F5C56B` / `rgba(242,178,92,.30)` | `#DC6803` (L) / `#D98A2B` (D) |
| Danger | `#B42318` / `#F28B82` | `#FEF3F2` / `rgba(242,139,130,.12)` | `#F4A9A3` / `rgba(242,139,130,.30)` | `#B42318` |

\* **Success and info badges in dark mode use white text** (`--ds-badge-success-text`, `--ds-badge-info-text`, `--ds-badge-accent-text`). The colour comes from the tint, border and dot. Warning (amber) and danger (red) keep coloured text, because they aren't green.

### 3.7 Chart palette

| # | Light | Dark |
|---|---|---|
| 1 | `#0B3D2E` | `#2DD4BF` |
| 2 | `#16AB6D` | `#5FD39A` |
| 3 | `#2DD4BF` | `#C9F0DB` |
| 4 | `#5C7A6E` | `#9FBDB1` |
| 5 | `#9FBDB1` | `#6CC8D6` |
| 6 | `#0E6F78` | `#16AB6D` |
| 7 | `#B42318` | `#F28B82` |
| 8 | `#B54708` | `#F2B25C` |
| Grid | `rgba(11,61,46,.08)` | `#17362B` |

## 4. Typography

- **Font:** `Inter, "Inter var", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif`.
- **Monospace:** `"JetBrains Mono", "SF Mono", "Cascadia Code", Menlo, Consolas, monospace`.
- **Base size:** 14px.

| Role | Size / line height | Weight (Light) | Weight (Dark) |
|---|---|---|---|
| Page title (h1) | 24px | 600 | 700 |
| Eyebrow above title | 13px / 20px, sentence case, secondary text | 500 | 600 |
| Panel title | 16px / 24px | 600 | 700 |
| KPI value | 28px | 700 | 700 |
| Body | 14px / 22px | 400 | 600 |
| Table text | 13px | 400 | 600 |
| Table header | 13px | 600 | 700 |
| Badge / chip | 12px | 500 | 600 |
| Caption / helper | 12px | 400 | 600 |

**Dark mode is one step bolder.** It only overrides the weight tokens:

| Token | Light | Dark |
|---|---|---|
| `--ds-weight-regular` | 400 | 600 |
| `--ds-weight-medium` | 500 | 600 |
| `--ds-weight-semibold` | 600 | 700 |
| `--ds-weight-bold` | 700 | 700 |

Always set weights through these tokens, never as literal numbers, so the dark-mode bump applies everywhere.

## 5. Spacing, shape, elevation

| Item | Value |
|---|---|
| Spacing scale | 4px base: 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64 |
| Card padding | 20px (16px on phones) |
| Radius | xs 2 · sm 4 · md 6 · lg 8 · card 12 · pill 9999 |
| Control heights | buttons and inputs 40px · small buttons 32px · table header 44px · sidebar items 40px |
| Sidebar width | 248px (64px icon rail on tablet) |
| Header height | 64px |
| Light card shadow | `0 1px 2px rgba(9,35,28,.06), 0 4px 12px rgba(9,35,28,.04)` |
| Dark card shadow | none (borders carry the edges) |
| Motion | 80 / 120 / 180 / 240 ms with `cubic-bezier(.2,0,0,1)`. Honour `prefers-reduced-motion`. |

## 6. Component recipes

| Component | Light | Dark |
|---|---|---|
| **Page** | White canvas. The header sits on the canvas with a hairline bottom border; it gains `--ds-shadow-header` when the page scrolls. | Same layout on `#07160F` |
| **Card / panel** | White, 1px `--ds-border-default`, **3px `#0B3D2E` top border**, radius 12, light shadow | `#0B2119`, 1px `#1F4336` on all sides, no shadow |
| **KPI card** | Card + 36px icon tile (radius 8, status tint), 28px bold value, label in secondary text | Same, with white text |
| **Primary button** | `#0F7F50` fill, white text, 40px tall, radius 8, padding 0 16px, weight 600, no shadow | Same fill, white text, weight 700 |
| **Secondary button** | `#C9F0DB` fill, primary text, no border | `#0F2A20` fill, white text, `#2A5546` border |
| **Input** | 40px, white, border `--ds-border-input`, hover `#0B3D2E`, focus 2px ring `#0F7F50` | 40px, `#04100B`, border `#4D7A69`, focus ring `#2DD4BF` |
| **Table** | `th` `#E9FFF4`, 44px, 13px semibold. `td` white. Hover mint 35%. Selected `#C9F0DB` + 3px left indicator. | `th` `#0F2A20`, `td` transparent, teal hover, white text |
| **Badge / pill** | Height 20–24px, pill radius, 12px, tint + 1px border + optional 6px dot | Same shape. Green and teal badges use white text. |
| **Tabs** | Underline in the focus-ring colour | Same, teal |
| **Sidebar item** | 40px, radius 8. Active: `--ds-shell-active-bg`, white text, 3px teal bar on the left edge. | Same |
| **Links** | `#0B6E45` semibold | White semibold, underline on hover |
| **Progress bar** | 6px, track `#C9F0DB`, fill `#16AB6D` | Track `#17362B`, fill `#2DD4BF` |
| **Focus** | 2px outline, 2px offset, `--ds-focus-ring` | Same |

## 7. Accessibility (measured contrast)

All text pairs meet WCAG 2.1 AA (4.5:1 for body text).

| Pair | Ratio |
|---|---|
| Light: primary text on white | 14.92 |
| Light: secondary text on white / on mint selection | 5.86 / 4.74 |
| Light: link `#0B6E45` on white | 6.31 |
| Light: table header text on `#E9FFF4` | 14.26 |
| Light: sidebar text / label on `#0B3D2E` | 9.86 / 6.04 |
| Both: white on primary button `#0F7F50` | 5.03 |
| Dark: primary / secondary / tertiary text on surface | 16.86 / 11.66 / 8.13 |
| Dark: sidebar text / label on `#082A20` | 14.05 / 8.02 |
| Dark: button fill against canvas (non-text, needs 3:1) | 3.69 |

Two of these values deliberately differ from the original Green & Mint spec:

- **Light muted text** is `#4D6B5F`. The spec's `#5C7A6E` drops to 3.8:1 on mint.
- **Dark-mode primary buttons** use `#0F7F50` with white text. White on bright teal `#2DD4BF` would fail contrast.

## 8. Rules

1. **Colours:** use tokens only. A new colour means a new token, defined for **both** themes.
2. **Selectors:** define a theme value under `[data-theme="light"]` / `[data-theme="dark"]`. Don't put a single-theme value in a bare `:root` block that appears later in the file, because `:root` also matches in light mode and would override it.
3. **Dark mode text:** use white or neutral grey only. Green is for fills, borders, dots, icons and selection.
4. **Light mode cards:** white with the 3px dark-green top border. Don't tint the page or the cards green.
5. **Font weights:** use the weight tokens, so dark mode stays one step bolder.
6. **Status:** never show status by colour alone. Pair it with a label, dot or icon.
7. **Checking:** test every change at phone (390px), tablet (768px) and desktop (1366px, 1920px) widths, in both themes.

## 9. Starter kit

Copy these three pieces into a new project.

### 9.1 `theme.css` (tokens)

```css
/* Green & Mint — dark is the default; light applies with data-theme="light". */
:root, [data-theme="dark"] {
  color-scheme: dark;
  --ds-bg-canvas: #07160F;  --ds-bg-surface: #0B2119;  --ds-bg-raised: #0F2A20;  --ds-bg-sunken: #04100B;
  --ds-bg-input: #04100B;   --ds-bg-hover: rgba(45,212,191,.06);  --ds-bg-selected: rgba(45,212,191,.14);
  --ds-bg-neutral-tint: rgba(201,240,219,.06);  --ds-bg-disabled: #18342A;  --ds-bg-tooltip: #1A4033;
  --ds-table-head: #0F2A20; --ds-table-body: transparent;  --ds-table-row-hover: rgba(45,212,191,.06);

  --ds-text-primary: #FFFFFF; --ds-text-secondary: #D2D8D5; --ds-text-tertiary: #AEB6B2; --ds-text-disabled: #9AA39F;
  --ds-text-accent: #FFFFFF;  --ds-on-fill-strong: #FFFFFF;

  --ds-fill-strong: #0F7F50; --ds-fill-strong-hover: #0B6E45; --ds-fill-strong-active: #0B5E3B;
  --ds-accent: #2DD4BF; --ds-accent-indicator: #2DD4BF; --ds-accent-subtle: rgba(45,212,191,.14); --ds-accent-border: rgba(45,212,191,.30);
  --ds-focus-ring: #2DD4BF;
  --ds-btn-secondary-bg: #0F2A20; --ds-btn-secondary-text: #FFFFFF; --ds-btn-secondary-border: #2A5546;

  --ds-border-subtle: #17362B; --ds-border-default: #1F4336; --ds-border-strong: #2A5546;
  --ds-border-input: #4D7A69;  --ds-border-input-hover: #6A9886;
  --ds-card-top-width: 1px; --ds-card-top-color: #1F4336; --ds-card-shadow: none;

  --ds-shell-bg: #082A20; --ds-shell-active-bg: #041A13; --ds-shell-hover: rgba(201,240,219,.07);
  --ds-shell-text: #F2F5F4; --ds-shell-text-hi: #FFFFFF; --ds-shell-label: #B4BDB9; --ds-shell-accent: #2DD4BF;
  --ds-shell-border: rgba(201,240,219,.08);
  --ds-brand-tile-bg: #0F7F50; --ds-brand-tile-fg: #FFFFFF; --ds-count-bg: #0F7F50; --ds-count-fg: #FFFFFF;

  --ds-success: #5FD39A; --ds-success-subtle: rgba(95,211,154,.12); --ds-success-border: rgba(95,211,154,.30);
  --ds-info: #6CC8D6;    --ds-info-subtle: rgba(108,200,214,.12);  --ds-info-border: rgba(108,200,214,.30);
  --ds-warning: #F2B25C; --ds-warning-subtle: rgba(242,178,92,.12); --ds-warning-border: rgba(242,178,92,.30);
  --ds-danger: #F28B82;  --ds-danger-subtle: rgba(242,139,130,.12); --ds-danger-border: rgba(242,139,130,.30);
  --ds-badge-success-text: #FFFFFF; --ds-badge-info-text: #FFFFFF; --ds-badge-accent-text: #FFFFFF;

  --ds-weight-regular: 600; --ds-weight-medium: 600; --ds-weight-semibold: 700; --ds-weight-bold: 700;
}

[data-theme="light"] {
  color-scheme: light;
  --ds-bg-canvas: #FFFFFF;  --ds-bg-surface: #FFFFFF;  --ds-bg-raised: #F7FFF9;  --ds-bg-sunken: #EEF8F2;
  --ds-bg-input: #FFFFFF;   --ds-bg-hover: rgba(201,240,219,.50);  --ds-bg-selected: #C9F0DB;
  --ds-bg-neutral-tint: #EEF3F1;  --ds-bg-disabled: #E3ECE8;  --ds-bg-tooltip: #052D22;
  --ds-table-head: #E9FFF4; --ds-table-body: #FFFFFF;  --ds-table-row-hover: rgba(201,240,219,.35);

  --ds-text-primary: #0F2C25; --ds-text-secondary: #4D6B5F; --ds-text-tertiary: #4D6B5F; --ds-text-disabled: #8AA39A;
  --ds-text-accent: #0B6E45;  --ds-on-fill-strong: #FFFFFF;

  --ds-fill-strong: #0F7F50; --ds-fill-strong-hover: #0B6E45; --ds-fill-strong-active: #0B3D2E;
  --ds-accent: #0F7F50; --ds-accent-indicator: #16AB6D; --ds-accent-subtle: #C9F0DB; --ds-accent-border: rgba(22,171,109,.40);
  --ds-focus-ring: #0F7F50;
  --ds-btn-secondary-bg: #C9F0DB; --ds-btn-secondary-text: #0F2C25; --ds-btn-secondary-border: transparent;

  --ds-border-subtle: rgba(11,61,46,.08); --ds-border-default: rgba(11,61,46,.10); --ds-border-strong: rgba(11,61,46,.18);
  --ds-border-input: rgba(11,61,46,.55);  --ds-border-input-hover: #0B3D2E;
  --ds-card-top-width: 3px; --ds-card-top-color: #0B3D2E;
  --ds-card-shadow: 0 1px 2px rgba(9,35,28,.06), 0 4px 12px rgba(9,35,28,.04);

  --ds-shell-bg: #0B3D2E; --ds-shell-active-bg: #052D22; --ds-shell-hover: rgba(201,240,219,.08);
  --ds-shell-text: #C9F0DB; --ds-shell-text-hi: #FFFFFF; --ds-shell-label: #9FBDB1; --ds-shell-accent: #2DD4BF;
  --ds-shell-border: rgba(201,240,219,.08);
  --ds-brand-tile-bg: #2DD4BF; --ds-brand-tile-fg: #0B3D2E; --ds-count-bg: #2DD4BF; --ds-count-fg: #052D22;

  --ds-success: #0B6E45; --ds-success-subtle: #C9F0DB; --ds-success-border: #16AB6D;
  --ds-info: #0E6F78;    --ds-info-subtle: #E6FBF8; --ds-info-border: #2DD4BF;
  --ds-warning: #B54708; --ds-warning-subtle: #FFFAEB; --ds-warning-border: #F5C56B;
  --ds-danger: #B42318;  --ds-danger-subtle: #FEF3F2; --ds-danger-border: #F4A9A3;
  --ds-badge-success-text: #0B6E45; --ds-badge-info-text: #0E6F78; --ds-badge-accent-text: #0B6E45;

  --ds-weight-regular: 400; --ds-weight-medium: 500; --ds-weight-semibold: 600; --ds-weight-bold: 700;
}

/* Shared, theme-independent tokens */
:root {
  --ds-font-sans: Inter, "Inter var", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
  --ds-radius-sm: 4px; --ds-radius-md: 6px; --ds-radius-lg: 8px; --ds-radius-card: 12px; --ds-radius-full: 9999px;
  --ds-sidebar-width: 248px; --ds-header-height: 64px;
  --ds-ease: cubic-bezier(.2,0,0,1); --ds-fast: .12s; --ds-base: .18s;
}
.ds-theme-switching, .ds-theme-switching * { transition: none !important; }
```

### 9.2 `components.css` (core recipes)

```css
body { margin: 0; font: var(--ds-weight-regular) 14px/22px var(--ds-font-sans); color: var(--ds-text-primary); background: var(--ds-bg-canvas); }
:where(input, textarea, select, button) { font-family: inherit; font-weight: var(--ds-weight-regular); }
:focus-visible { outline: 2px solid var(--ds-focus-ring); outline-offset: 2px; }

/* Sidebar */
.sidebar { width: var(--ds-sidebar-width); background: var(--ds-shell-bg); color: var(--ds-shell-text); padding: 16px 12px; }
.sidebar-label { color: var(--ds-shell-label); font: var(--ds-weight-semibold) 12px/16px var(--ds-font-sans); padding: 14px 12px 6px; }
.sidebar-item { position: relative; display: flex; align-items: center; gap: 12px; height: 40px; padding: 0 12px; border-radius: 8px;
  color: var(--ds-shell-text); font-weight: var(--ds-weight-semibold); text-decoration: none; }
.sidebar-item:hover { background: var(--ds-shell-hover); }
.sidebar-item[aria-current="page"] { background: var(--ds-shell-active-bg); color: var(--ds-shell-text-hi); }
.sidebar-item[aria-current="page"]::before { content: ""; position: absolute; left: -8px; top: 8px; bottom: 8px; width: 3px;
  border-radius: 0 3px 3px 0; background: var(--ds-shell-accent); }
.sidebar-count { margin-left: auto; min-width: 24px; height: 20px; padding: 0 7px; border-radius: var(--ds-radius-full);
  display: inline-grid; place-items: center; background: var(--ds-count-bg); color: var(--ds-count-fg); font-size: 12px; font-weight: var(--ds-weight-semibold); }

/* Page header */
.page-header { padding: 24px 32px 16px; border-bottom: 1px solid var(--ds-border-default); }
.page-header h1 { margin: 0; font: var(--ds-weight-semibold) 24px/32px var(--ds-font-sans); color: var(--ds-text-primary); }
.page-header .eyebrow { font: var(--ds-weight-medium) 13px/20px var(--ds-font-sans); color: var(--ds-text-secondary); }

/* Card — the 3px dark-green top border shows in light mode */
.card { background: var(--ds-bg-surface); border: 1px solid var(--ds-border-default); border-radius: var(--ds-radius-card);
  border-top: var(--ds-card-top-width) solid var(--ds-card-top-color); box-shadow: var(--ds-card-shadow); padding: 20px; }
.card-title { font: var(--ds-weight-semibold) 16px/24px var(--ds-font-sans); margin: 0 0 12px; }
.kpi-value { font: var(--ds-weight-bold) 28px/34px var(--ds-font-sans); font-variant-numeric: tabular-nums; }

/* Buttons */
.btn { height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid transparent; font-weight: var(--ds-weight-semibold); cursor: pointer;
  display: inline-flex; align-items: center; gap: 8px; transition: background-color var(--ds-fast) var(--ds-ease); }
.btn-sm { height: 32px; padding: 0 12px; }
.btn-primary { background: var(--ds-fill-strong); color: var(--ds-on-fill-strong); }
.btn-primary:hover { background: var(--ds-fill-strong-hover); }
.btn-primary:active { background: var(--ds-fill-strong-active); }
.btn-secondary { background: var(--ds-btn-secondary-bg); color: var(--ds-btn-secondary-text); border-color: var(--ds-btn-secondary-border); }
.btn:disabled { background: var(--ds-bg-disabled); color: var(--ds-text-disabled); cursor: not-allowed; }

/* Inputs */
.input { height: 40px; padding: 0 12px; border-radius: 8px; background: var(--ds-bg-input); color: var(--ds-text-primary);
  border: 1px solid var(--ds-border-input); }
.input:hover { border-color: var(--ds-border-input-hover); }

/* Tables */
.table { width: 100%; border-collapse: collapse; font-size: 13px; }
.table th { height: 44px; padding: 0 12px; text-align: left; background: var(--ds-table-head); font-weight: var(--ds-weight-semibold); }
.table td { padding: 12px; background: var(--ds-table-body); border-top: 1px solid var(--ds-border-subtle); }
.table tbody tr:hover td { background: var(--ds-table-row-hover); }
.table tr[aria-selected="true"] td { background: var(--ds-bg-selected); }
.table tr[aria-selected="true"] td:first-child { box-shadow: inset 3px 0 0 var(--ds-accent-indicator); }

/* Badges */
.badge { display: inline-flex; align-items: center; gap: 6px; height: 22px; padding: 0 8px; border-radius: var(--ds-radius-full);
  border: 1px solid; font: var(--ds-weight-medium) 12px/1 var(--ds-font-sans); white-space: nowrap; }
.badge-dot::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.badge-success { background: var(--ds-success-subtle); border-color: var(--ds-success-border); color: var(--ds-badge-success-text); }
.badge-info    { background: var(--ds-info-subtle);    border-color: var(--ds-info-border);    color: var(--ds-badge-info-text); }
.badge-accent  { background: var(--ds-accent-subtle);  border-color: var(--ds-accent-border);  color: var(--ds-badge-accent-text); }
.badge-warning { background: var(--ds-warning-subtle); border-color: var(--ds-warning-border); color: var(--ds-warning); }
.badge-danger  { background: var(--ds-danger-subtle);  border-color: var(--ds-danger-border);  color: var(--ds-danger); }
.badge-neutral { background: var(--ds-bg-neutral-tint); border-color: var(--ds-border-default); color: var(--ds-text-secondary); }
.badge-success.badge-dot::before, .badge-info.badge-dot::before, .badge-accent.badge-dot::before { background: var(--ds-accent-indicator); }

/* Links */
a { color: var(--ds-text-accent); font-weight: var(--ds-weight-semibold); text-decoration: none; }
a:hover { text-decoration: underline; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
```

### 9.3 Theme switching (HTML + JS)

Put this in `<head>`, **before** any stylesheet, so the first paint uses the right theme:

```html
<meta name="color-scheme" content="dark light" />
<script>
  (function () {
    var pref = 'system';
    try { var v = localStorage.getItem('ds-theme'); if (v === 'light' || v === 'dark') pref = v; } catch (e) {}
    var light = pref === 'light' || (pref === 'system' && matchMedia('(prefers-color-scheme: light)').matches);
    document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
  })();
</script>
```

This is the controller for the Light / Dark / System switch:

```js
const KEY = 'ds-theme';
const media = matchMedia('(prefers-color-scheme: light)');

export function getPreference() {
  try { const v = localStorage.getItem(KEY); if (v === 'light' || v === 'dark') return v; } catch {}
  return 'system';
}

function apply(pref) {
  const theme = pref === 'system' ? (media.matches ? 'light' : 'dark') : pref;
  const root = document.documentElement;
  if (root.getAttribute('data-theme') === theme) return;
  root.classList.add('ds-theme-switching');            // swap every component at once
  root.setAttribute('data-theme', theme);
  requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('ds-theme-switching')));
}

export function setPreference(pref) {                  // 'light' | 'dark' | 'system'
  try { pref === 'system' ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, pref); } catch {}
  apply(pref);
}

export function initTheme() {
  apply(getPreference());
  media.addEventListener('change', () => { if (getPreference() === 'system') apply('system'); });
  addEventListener('storage', (e) => { if (e.key === KEY) apply(getPreference()); });   // other tabs
}
```

Switch markup: three buttons with `aria-pressed`, placed at the bottom of the sidebar.

```html
<div class="theme-toggle" role="group" aria-label="Colour theme">
  <button type="button" data-pref="light"  aria-pressed="false">Light</button>
  <button type="button" data-pref="dark"   aria-pressed="false">Dark</button>
  <button type="button" data-pref="system" aria-pressed="true">System</button>
</div>
```

## 10. Where it lives in this POC

| File | What it holds |
|---|---|
| `frontend/index.html` | Pre-paint theme script |
| `frontend/src/theme.ts` | Theme controller (Light / Dark / System, OS and other-tab sync) |
| `frontend/src/tokens.css` | All `--ds-*` tokens. **Later blocks override earlier ones.** The "Green & Mint" block and the appended blocks after it are the current values. |
| `frontend/src/design-system.css` | Component styles. Loaded last. The "Green & Mint" section and the blocks after it are current. |
| `frontend/src/theme.css`, `index.css`, `components.css` | Older aliases (`--color-*`) mapped onto the `--ds-*` tokens |

CSS load order: `tokens.css → base.css → theme.css → index.css → workflow.css → components.css → design-system.css`.
