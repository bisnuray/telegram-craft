# Mini App engineering

Use for launch, auth, SDK use, viewport handling, and client/server flows. For visual design see `mini-app-design.md`.

## Launch surfaces

| Launch | Data flow | Notes |
|---|---|---|
| Keyboard button | `Telegram.WebApp.sendData` to the bot; closes the app | Only this launch type can use `sendData`; up to 4096 bytes |
| Inline button | Backend + `answerWebAppQuery` with `query_id` | Private chats only |
| Menu button | Backend + `answerWebAppQuery` | |
| Direct link `t.me/bot/app?startapp=x` | Backend | `start_param` is untrusted |
| Main Mini App | Backend | `t.me/bot?startapp` |
| Inline mode, attachment menu | Backend | |

Treat `start_param` as untrusted input: validate its format with your own rules and authorize the target on the server.

## Bootstrap

```html
<head>
  <script src="https://telegram.org/js/telegram-web-app.js?64"></script>
  <!-- then your bundle -->
</head>
```

The `?64` version query is what the docs showed on 2026-11-08; copy the current one from `tgdocs.py page bots/webapps --section "Initializing"`. Call `Telegram.WebApp.ready()` as soon as essential UI can display, so that the loading placeholder is hidden. Call `expand()` if the task needs full height. Outside Telegram `initData` is empty: show a clear "Open in Telegram" state and allow a mock in development only.

## Authentication

```
client  → Authorization: tma <raw initData>   (or exchange once for a session)
server  → validate HMAC, check auth_date, then look up the user and permissions
```

Rules:

- Send the raw `initData` string. Never derive identity from `initDataUnsafe` or a `user_id` in the body.
- Server check: `HMAC_SHA256(key=HMAC_SHA256(key="WebAppData", msg=token), msg=data_check_string)`, compared in constant time. The string covers **all received fields except `hash`**, sorted, one per line. `signature` is included for this check.
- Check `auth_date`. Telegram leaves this to you. Use a short window for sensitive actions, or exchange init data for a short-lived server session. Long-lived tabs need a refresh path: when the session lapses, re-read `Telegram.WebApp.initData`, and tell users to reopen if it is too old.
- For verification by a third party without the token, use the Ed25519 `signature` flow. That check excludes both `hash` and `signature` and prefixes `bot_id:WebAppData`. Copy the public key from the docs.
- Set CORS to your origin only. Rate-limit by validated user. Authorize each object.
- The token lives on the server. Build tools embed anything named `VITE_*` or `NEXT_PUBLIC_*` in client code.

## Origin hardening (Bot API 10.2)

Since 2026-07-20, Mini App methods are blocked from origins other than the app's own domain by default. Iframes from other origins cannot use the WebApp API, and redirects to another domain lose access. Keep the app on one origin or expect this to break it. Opting out in @BotFather makes the owner responsible for keeping untrusted links out.

## Viewport and safe areas

- Use `var(--tg-viewport-stable-height)` to pin bottom content, not `100vh`, which is wrong in webviews. `--tg-viewport-height` changes continuously during drag.
- Fullscreen (8.0+) needs both insets: `--tg-safe-area-inset-*` for device cutouts and `--tg-content-safe-area-inset-*` for Telegram's controls. Combine them at the top.
- Vertical swipes minimize the app. Only call `disableVerticalSwipes()` (7.7+) when your own gestures conflict.
- The keyboard changes height differently per platform. Keep inputs in view and don't anchor to a stale height.

## Native controls

| Control | Use | Version |
|---|---|---|
| `BackButton` | Nested routes. Show on depth above 0 and connect it to the router. | 6.1 |
| `MainButton`/`BottomButton` | The screen's one main action | Base; `SecondaryButton` 7.10 |
| `showPopup`, `showConfirm`, `showAlert` | Native dialogs | 6.2 |
| `enableClosingConfirmation` | Unsaved changes only | 6.2 |
| `HapticFeedback` | Confirmed success, error, or selection | 6.1 |
| `setHeaderColor`, `setBackgroundColor`, `setBottomBarColor` | Match surfaces | 6.1–7.10 |
| `CloudStorage` | Small per-user non-sensitive data | 6.9 |
| `DeviceStorage`, `SecureStorage` | Device-local; secure for sensitive values | 9.0 |

Always guard with `isVersionAtLeast`, because clients differ and an unsupported call can throw or log an error. Unsubscribe handlers on route change, or stacked Back handlers will fire repeatedly.

Set the button's progress state during submit, and disable it to prevent double submission. The backend still needs idempotency.

## Theme

Read `themeParams` and CSS variables `--tg-theme-*` (`bg-color`, `text-color`, `hint-color`, `link-color`, `button-color`, `button-text-color`, `secondary-bg-color`, `header-bg-color`, `bottom-bar-bg-color`, `accent-text-color`, `section-bg-color`, `section-header-text-color`, `section-separator-color`, `subtitle-text-color`, `destructive-text-color`). Listen for `themeChanged`. Provide fallbacks for older clients.

## Bot and Mini App together

- Share one backend and one user record keyed by Telegram ID.
- Use the bot to notify, and deep-link into a specific screen with `startapp`.
- The message after a Mini App purchase should be sent by the server, from the `successful_payment` update.
- Payments: create the invoice link on the server and call `openInvoice(url, callback)`. Use the callback for UI only.
- Ask for write access (`requestWriteAccess`) or contact only upon a user action, with a reason.

## Client/server reliability

Use timeouts, retry idempotent reads, and send an idempotency key on writes. Show offline and error states. On `activated`/`deactivated` (8.0+), pause polling and animation.

## Frontend code

Mini App code is a small production frontend. The general standard (`code-quality.md`) applies; these are the Mini App specifics.

- **TypeScript in `strict` mode.** No `any` at boundaries: type API responses as `unknown`, then validate them (with the project's validator, such as zod or valibot, or a small type guard) before use. Type the `Telegram.WebApp` object once in one module, instead of `(window as any)` in every file.
- **Identity never comes from the client.** Send the raw `initData` string and let the server validate it (Authentication, above). `initDataUnsafe` is for display only. Secrets and admin tokens never ship in the bundle.
- **Every subscription is cleaned up.** Register `onEvent`, `MainButton.onClick`, `BackButton.onClick`, and `setInterval` inside an effect, and return the matching `offEvent` or `offClick`. Registering in a component body adds a new handler on every render, so one tap fires many times.
- **Every request has three states:** loading, error, and data. Check `response.ok`, catch failures, cancel stale requests with `AbortController`, and show an error the user can retry.
- **Components:** one component per screen, presentational parts split out when reused, and state kept as local as possible. Use the server-state library the project already has (TanStack Query, SWR) instead of hand-rolled caches.
- **Tooling:** run `tsc --noEmit` and the project's ESLint config (`typescript-eslint` recommended plus `react-hooks/exhaustive-deps` in React projects). Add Prettier only if the project uses it. Do not add a second tool for a job one already does.

## Debugging

- iOS: tap Settings 10 times, enable Allow Web View Inspection, and use Safari.
- Android: enable USB debugging. In Telegram Settings, press and hold the version number twice and choose Enable WebView Debug, then use `chrome://inspect`.
- Telegram Desktop Beta (Windows, Linux): Settings > Advanced > Experimental settings > Enable webview inspection.
- Test environment: `https://api.telegram.org/bot<token>/test/METHOD`, where HTTP links are allowed.

The Android User-Agent includes a performance class. Reduce effects on low-end devices.

## Testing

Use `assets/webapp_mock.js` to preview in light and dark and with insets, at 360×640 and 390×844. Test the validator with forged, expired, and tampered data. Label those results L2, and test on a real client before claiming L3.
