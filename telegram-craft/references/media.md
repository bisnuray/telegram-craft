# Media and file processing

Use for music, audio, video, conversion, and file-utility bots. Start from `assets/media_job.py`.

## Limits that shape the design

| Operation | Cloud Bot API | Local Bot API server |
|---|---|---|
| Download via `getFile` | 20 MB | No limit |
| Upload, photo | 10 MB | Larger files per docs |
| Upload, other | 50 MB | 2000 MB |
| Send by URL | 5 MB photo, 20 MB other | n/a |
| Send by `file_id` | No documented limit | n/a |

Read `file_size` from the incoming object **before** downloading and refuse with the actual numbers. It may be absent, so also cap the bytes during download. If the product must handle larger files, run a local Bot API server, whose paths are shared with the app, and plan for disk space.

Download links contain the bot token, so never send or log them. They are valid for at least an hour.

## Pick the right send method

| Result | Method | Format |
|---|---|---|
| Song in the player | `sendAudio` | MP3 or M4A; set `title`, `performer`, `duration`, `thumbnail` |
| Voice bubble | `sendVoice` | OGG/Opus, MP3, or M4A |
| Video in the player | `sendVideo` | MPEG-4 (H.264/AAC is the safe choice); set `width`, `height`, `duration`, and `supports_streaming` |
| Round video | `sendVideoNote` | Square MPEG-4 |
| Exact file, no recompression | `sendDocument` | Anything |
| Album | `sendMediaGroup` | 2–10 items |

Thumbnails are JPEG, under 200 kB, at most 320 px per side, and must be uploaded fresh. Formats that clients do not support are best sent as documents. Probe output with `ffprobe` if it matters.

## Job pipeline

Slow media handling separates the handler from the job:

```
handler: validate → create job → reply "Queued" → return
worker:  claim → download → convert → verify → upload → cache → edit status → cleanup
```

For a small bot, the worker can be an `asyncio` task behind a semaphore. Use a persistent queue when jobs must survive restarts or more than one worker runs.

Requirements:

- **Global concurrency cap** sized to CPU, and a per-user cap so that one user can't fill the queue.
- **Timeout** per stage, killing the process group.
- **Disk budget**: a per-job workspace removed in `finally`, a startup sweep for leftovers from crashes, and a refusal when free space is low.
- **Limits**: input duration and resolution as well as bytes. A small file can decode to something enormous.
- **Dedupe in flight**: if the same source is already being processed, attach to that job.

## Running FFmpeg safely

```python
limiter = asyncio.Semaphore(max(1, (os.cpu_count() or 2) - 1))

async with job_workspace() as work:
    source = work / "input"          # server-chosen name, never the user's
    await bot.download(file_id, destination=source)
    target = work / "voice.ogg"
    await run_tool(ffmpeg_to_voice_argv(source, target), limiter, timeout_seconds=300)
    assert_uploadable(target)
    sent = await bot.send_voice(chat_id, FSInputFile(target))
```

- Use argv lists, never `shell=True`, and never put a user filename on a path. Sanitize the display name separately.
- Set `-protocol_whitelist file,pipe` on untrusted input so that playlists can't fetch URLs or read local files. Add `-nostdin`.
- Set `-map_metadata -1` if privacy matters.
- Process untrusted media in a low-privilege, resource-limited container where possible, and keep FFmpeg patched.
- For downloads from URLs (`yt-dlp` and similar): block private IP ranges and non-HTTP schemes to avoid SSRF, limit size and duration, and invoke with `--` before the URL so that it can't be read as an option. Confirm that the use is lawful and allowed by the source's terms. Refuse DRM circumvention.

## Caching

`file_id` values are persistent and reusable by the **same bot**, and resending by `file_id` is instant, so store them:

```
key: (source_hash or source_url, profile) → file_id, file_unique_id, created_at
```

- `file_unique_id` is stable across bots but cannot be used to send. Use it for dedupe.
- A `file_id` can't change type, so a video can't be resent as a photo.
- Handle a failed `file_id` by removing the cache row and regenerating.
- Cache keys must include conversion options and tool profile.
- When deleting user data, delete cache entries that identify the user.

## Progress and feedback

- Under 5 seconds: `sendChatAction` with the matching action (`upload_voice`, `upload_video`, `upload_document`, and so on). It lasts up to 5 seconds, so repeat every 4 seconds for longer work, and stop on completion.
- Longer: one status message, edited at stage changes or at most every 3 to 5 seconds. Ignore `message is not modified`. Parse real progress with `ffmpeg -progress pipe:1` if you need percentages. Otherwise show the stage.
- Offer Cancel on long jobs, and have it really stop the process.
- Replace the status message when finished, or delete it once the file arrives.

## Album input

Each album item arrives as a separate update sharing `media_group_id`. Buffer briefly, for about a second keyed by that ID, and then process them together. There's no end-of-album signal.

## Content and rights

Do not build features that bypass DRM or that exist mainly to redistribute copyrighted content. Add a report and takedown path for bots that host or share user media, and set `protect_content` for paid media.

## Testing

Use real FFmpeg on generated fixtures (`-f lavfi -i sine=...`). Include a corrupt file, a hostile filename, a file over the limit, a timeout, cancellation, and a disk-cleanup assertion after each.
