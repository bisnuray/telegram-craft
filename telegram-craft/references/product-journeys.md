# Product journeys

Use for new products, `/start`, onboarding, and any flow that spans several screens. Design the journey before the handlers: a bot is a graph of screens and states.

## Capture only what shapes the build

Work out from the request, then ask at most what is still blocking:

| Decide | Why it matters |
|---|---|
| The one job users come for | It becomes the first screen's main action |
| Who acts (user, admin, group member, channel) | Permissions, scopes, private or group surface |
| What must survive a restart | Decides whether a database is needed |
| Money involved? | Stars rules, ledger, `/paysupport` |
| Slow work? (conversion, AI, downloads) | Job queue and progress design |
| Languages | Strings must be externalized from day one |

Unknown details get a stated assumption. Do not invent business rules such as prices or refund windows: use a named config value and flag it.

## Screen map

Write this before code, even as a short table. It catches dead ends cheaply.

| Screen | Purpose | Shows | Actions | Goes to | Who |
|---|---|---|---|---|---|
| `home` | Start a conversion | Last job status | Convert, History, Settings | `pick`, `history`, `settings` | anyone |
| `history` | Find a past job | 5 per page | Item, Prev, Next, Back | `job`, `home` | owner |

For each screen also define **empty**, **loading**, **error**, **no permission**, and **expired** states. Most generated bots have only the happy path.

For multi-step work, write the state machine: states, the events that move between them, and what happens on `/cancel`, a timeout, or an unexpected input type (a photo where text was expected).

## `/start`

`/start` runs on first contact, on deep links, and every time a returning user taps it. Handle these differently:

| Situation | Show |
|---|---|
| New user | One line on what the bot does, then the main action |
| Returning user | Current state and the most likely next action |
| Deep link `/start ref_abc` | Go straight to that object after checking it exists and the user may see it |
| Invalid or expired payload | A short explanation, then home |
| Unfinished flow | Offer Resume or Start over |

Referrals need rules, because a link alone proves nothing:

- Use an opaque code, not a user ID. Attribute once per invitee, only for users who are actually new.
- Reject self-referral and unknown codes without blocking normal `/start`.
- Grant a reward only on a server-checked qualifying event, such as a first completed quiz or a successful payment. Opening a link is free to farm.
- Define the reward and the qualifying event even when the reward is a placeholder config value.

Rules:

- Never reset user data on `/start`.
- Treat the payload as untrusted input: allowed characters are `A-Za-z0-9_-`, up to 64.
- Do not explain every feature. Teach by making the first action obvious.
- Ask for permissions, contact, or location only at the moment they are needed, and say why.
- Set up `/help`, and `/settings` if applicable. Telegram asks bots to support these globally. Register commands with `setMyCommands` and use scopes for admin-only ones, but still authorize on the server, because scope only changes what is displayed.

## Onboarding

Value first. If setup is required, keep to the fewest steps that make the bot useful, show position ("Step 2 of 3"), allow Back at every step, and save partial answers.

## Multilingual products

- Select language from stored preference, then `language_code`, then a default. Offer a switch in settings.
- Keep every string in a catalog, including button labels, callback alerts, errors, and worker messages.
- Allow for text expansion: Russian and German labels often run longer than English, so check keyboard wrapping in the longest language.
- Plurals need real plural rules (Russian has several forms), not `count + "s"`.
- Prefer the `tg-time` entity for dates, which renders in the reader's locale.
- RTL languages reorder lines. Do not build alignment from spaces.

## Choosing Mini App versus chat

Keep it in chat when the task is one or two choices, or when the result should stay in the conversation. Move to a Mini App for filtering, browsing many items, complex forms, or visual selection. In hybrids, the bot handles entry, notifications, and results, while the Mini App handles the rich task. Return to chat with a confirmation message that a user can find later.

## Definition of a coherent journey

- Every screen is reachable, and every screen has a way forward or out.
- The same action has the same name everywhere.
- A user who disappears for a week and taps an old button gets a sensible response.
- An interrupted flow can be resumed or cancelled.
