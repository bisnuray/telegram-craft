# Groups, channels, and automation

Use for moderation, permissions, inline mode, ephemeral messages, AI bots, and bot-to-bot.

## What a bot can see

Privacy mode is on by default. In groups a bot then sees commands addressed to it, replies to it, service messages, and a few others. Admin bots receive all messages. Changing the privacy setting requires re-adding the bot to the group. Bots never see history from before they joined.

Enable `chat_member` in `allowed_updates` to track joins and leaves reliably; the bot must be an admin. Reactions need `message_reaction` and admin rights.

## Moderation bots

- Verify bot rights with `getChatMember` before acting, and tell an admin what's missing rather than failing silently.
- Verify the acting user's admin status from Telegram, with a short cache at most. Handle anonymous admins (`GroupAnonymousBot`, `sender_chat`), who have no usable `from`.
- Channel-linked posts and messages sent as a channel have `sender_chat`.
- Telegram's group limit is 20 messages per minute. Don't announce every action; delete notices after a short time or use ephemeral messages.
- Prefer graduated, reversible actions (warn, restrict with `until_date`, ban), and audit-log them with the reason.
- A group can turn into a supergroup: handle `migrate_to_chat_id`.
- Topic groups need `message_thread_id` on replies. FSM key strategy may need to be per topic.
- CAPTCHA and join flows: use `chat_join_request` when available. Time out and clean up. Remember that a new member may never be able to send a message or may be a bot.
- Don't flag users automatically on weak signals without a way to appeal.

## Buttons in shared chats

An inline keyboard is visible to everyone. Bind sensitive buttons to a user ID in callback data, verify `callback.from_user.id`, and use `show_alert` for others. Editing a shared message changes it for everyone, so use private chat or an ephemeral message for personal menus.

## Ephemeral messages (Bot API 10.2+, parameters changed in 10.3 and 10.4)

Visible to one user, and delivered within 15 seconds of an eligible action. Use `ephemeral_message_parameters`. Delivery isn't guaranteed, and these are edited through their own `editEphemeralMessage…` methods. `receiver_user_id` as a top-level send parameter existed only in 10.2, so check the docs and the SDK.

Since 10.4, a button press in any chat except channel direct-message chats can get a private reply. Pass `callback_query_id` and omit `receiver_user_id`; `chat_id` is then ignored. `replace_callback_query_message` shows it in place of the original message. You must still call `answerCallbackQuery`. This is the cleanest answer to a personal menu in a group. No SDK supported it on release day.

## Channels

Bots post as the channel and need the relevant admin rights. Scheduled publishing needs your own scheduler and persistence. Use `protect_content` where needed. Channel posts arrive as `channel_post`, with no `from`.

## Inline mode

Enable in @BotFather. Answer quickly. `cache_time` applies across users unless `is_personal` is true, so personal results must set it. Paginate with `next_offset`. Escape text in `input_message_content`.

## Scheduling and automation

Use a persistent schedule (a database and worker, or APScheduler with a persistent job store). Store timezone per user, and use UTC internally. Make runs idempotent with a key for each scheduled occurrence, and define catch-up behavior after downtime.

## Business, managed, and guest bots

These surfaces are newer. Read `tgdocs.py page bots/features --toc` before designing for them. Business bots act on behalf of a business account within granted rights. Guest bots answer in chats they haven't joined, so don't assume there's chat membership or permission.

## AI assistants

- Stream with drafts in private chats (`formatting.md`), and use a typing action and a final reply in groups.
- Rate-limit and meter usage per user, and set a budget.
- Keep conversation context bounded, in your own store. Topics in private chats can separate threads.
- Render model output safely. It's untrusted, and it may be long, so split or use a rich message.
- Tools take the authenticated user's permissions, never what the model claims.
- Tell users when AI is responding, and when content goes to a third-party processor.

## Bot-to-bot

Telegram requires safeguards against infinite loops. Ignore your own messages, limit depth and rate per conversation, and stop on repetition.
