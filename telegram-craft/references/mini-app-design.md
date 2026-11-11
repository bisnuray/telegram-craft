# Mini App design quality

Use for layout, type, color, motion, and states. A Mini App is a screen inside a chat client: it should feel native and purposeful, not like a landing page.

## Start from the task

Before styling, write three lines: the one thing this screen is for, what the user needs to see to do it, and the single main action. Then decide on the visual direction from the product. A wallet needs numeric clarity. A food menu needs imagery and appetite. An admin tool needs density and calm. A game may break convention entirely.

Telegram's own [design guidelines](https://core.telegram.org/bots/webapps#design-guidelines) ask for mobile-first layouts, interactive elements that match existing UI components, smooth animation, labelled inputs and images, theme-based colors, and respect for safe areas.

## Generic patterns to avoid by default

These aren't forbidden. They need a reason from the product.

- A purple-to-blue gradient hero or gradient-filled buttons
- Glassmorphism and blurred panels
- Identical rounded cards for everything, each with the same soft shadow
- A centered "Welcome to X" hero with a subtitle and big CTA
- A three-across stat row with big numbers and small labels
- Emoji used as an icon system
- Fade-and-rise animation on every element
- Decorative blobs or background gradients
- All-caps eyebrow labels over each section
- A custom bottom CTA that duplicates or fights `MainButton`

## Native first

- Use Telegram's Back and bottom buttons instead of drawing your own.
- Build surfaces from theme variables so that the app matches any user theme. Brand color belongs in small, deliberate places.
- Grouped list rows on `secondary-bg-color`, with `section-bg-color` sections and `section-separator-color` hairlines, read as native, and are a good default for settings and lists.
- Match platform conventions where they differ. `Telegram.WebApp.platform` tells you which you're on.
- If you hard-code a color, verify it against both light and dark themes and a colored custom theme.

```css
:root {
  --bg: var(--tg-theme-secondary-bg-color, #f4f4f5);
  --surface: var(--tg-theme-section-bg-color, #fff);
  --text: var(--tg-theme-text-color, #000);
  --muted: var(--tg-theme-hint-color, #707579);
  --accent: var(--tg-theme-button-color, #3390ec);
  --sep: var(--tg-theme-section-separator-color, rgba(0,0,0,.12));
}
body { background: var(--bg); color: var(--text); }
.screen {
  padding-top: calc(var(--tg-safe-area-inset-top, 0px) + var(--tg-content-safe-area-inset-top, 0px));
  padding-bottom: calc(16px + var(--tg-safe-area-inset-bottom, 0px));
  min-height: var(--tg-viewport-stable-height, 100vh);
}
```

## Hierarchy and type

- One clear focal point per screen. If everything is emphasized, nothing is.
- Use the system font stack by default, which is what Telegram uses. A custom font needs a brand reason and costs load time. Self-host and subset it.
- Use a small type scale, such as 13, 15, 17, 22, and 28 px, and vary weight before size.
- Use body text at 15–17 px. Secondary text should be no smaller than 13 px.
- Use `font-variant-numeric: tabular-nums` for prices, stats, and tables.
- Keep body line length comfortable, and truncate only with a way to see the full value.

## Spacing and density

Use a 4 px base and a few steps (4, 8, 12, 16, 24, 32). Group related items by proximity. Screen gutters of 16 px are typical. Density should fit the task: a list of 50 orders needs compact rows, while a checkout needs room.

## Touch and accessibility

| Check | Target |
|---|---|
| Touch targets | At least 44×44 CSS px for primary controls (WCAG 2.2 AA minimum is 24×24) |
| Spacing | At least 8 px between adjacent targets |
| Body text contrast | At least 4.5:1 (AA) |
| Large text, icons, control boundaries | At least 3:1 |
| Inputs | Real `<label>`, correct `inputmode`, `autocomplete` |
| Images | Meaningful `alt` |
| Icon-only buttons | `aria-label` |
| Semantics | `button`, `a`, `nav`, headings; no clickable `div` |
| Motion | Honor `prefers-reduced-motion` |
| Zoom | Do not disable it if you can avoid it |

Theme colors vary, so check contrast against the actual values. `hint-color` on `secondary-bg-color` can come out low, so don't use it for important text. Do not rely on color alone to signal status.

## States

Design each one. They are part of the product.

| State | Good treatment |
|---|---|
| First load | Skeleton that matches the final layout; no spinner on a blank page |
| Refresh | Keep content visible and show a small indicator |
| Empty | Say why it's empty and give the next action |
| Error | Plain cause, Retry, and preserved input |
| Offline | Say so and keep cached content readable |
| Submitting | `MainButton.showProgress()` and block double taps |
| Success | Update the data; add a haptic and move on. Avoid a celebration screen for routine tasks. |
| No access | Explain and offer a way back |

## Motion

Motion should explain something: a transition between screens, an item being added, or a confirmed action. Keep it to 150–250 ms and animate only `transform` and `opacity`. Telegram asks for smooth 60 fps animation. Reduce effects on low-performance Android devices, and pause work when the app is deactivated.

## Performance

Webviews on mid-range Android are the constraint. Aim for a small initial bundle, split routes, lazy-load images with explicit dimensions to prevent layout shift, avoid big libraries for small needs, and virtualize long lists. Measure on a throttled profile.

## Review with screenshots

If browser tools are available, render with `assets/webapp_mock.js` at 360×640 and 390×844, using `?tgTheme=light` and `?tgTheme=dark`, and with `&tgInsetTop=59&tgContentTop=46&tgInsetBottom=34` for fullscreen. Inspect the images, not just the code:

- Does the main action stand out without decoration?
- Does any content sit beneath a control or a notch?
- Is any text low-contrast in dark mode?
- Would this layout be the same for a completely different product? If so, it isn't designed yet.

Fix what you find and re-capture. A mock screenshot is L2 evidence.
