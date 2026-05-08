# Bookcast

Turn your `.epub`, `.fb2`, and `.txt` books into a personal podcast feed you can
subscribe to in Apple Podcasts on iPhone. Runs locally on a Mac, exposed over
Tailscale. Local TTS only — no cloud API costs. **No login** — Tailscale is the
perimeter.

- **English** narration via [Kokoro](https://github.com/hexgrad/kokoro)
- **Russian** narration via [Silero](https://github.com/snakers4/silero-models) v4_ru
- **One show per book**, one episode per chapter, ordered for audiobook playback
  (`<itunes:type>serial</itunes:type>`)

## Quickstart

```bash
brew install uv ffmpeg
uv sync
uv run alembic upgrade head
```

Run the web app and the worker in two terminals:

```bash
# terminal 1
uv run uvicorn bookcast.main:app --host 127.0.0.1 --port 8000 --reload

# terminal 2
uv run python -m bookcast.worker
```

Open <http://127.0.0.1:8000>. There is no login — anyone who can reach the host
on port 8000 (or the Tailscale URL) can use the app, by design.

## Configuration

All settings come from environment variables, optionally via a `.env` file at the
project root.

| Variable | Default | Purpose |
|---|---|---|
| `BOOKCAST_BASE_URL` | `http://localhost:8000` | Public URL the iPhone reaches. Set to `https://<host>.<tailnet>.ts.net` on the Mac. |
| `BOOKCAST_DEFAULT_VOICE_EN` | `af_heart` | Default Kokoro voice. |
| `BOOKCAST_DEFAULT_VOICE_RU` | `xenia` | Default Silero voice. |
| `BOOKCAST_TTS_CHUNK_CHARS` | `480` | Max chars per TTS request — chunks make crashes resumable. |
| `BOOKCAST_MP3_BITRATE` | `64k` | mp3 bitrate. 64k mono ≈ 28 MB/hour. |
| `BOOKCAST_DATA_DIR` | `./data` | Where originals, mp3s, covers, model weights live. |

Example `.env` for a Mac mini deploy:

```env
BOOKCAST_BASE_URL=https://bookcast.<your-tailnet>.ts.net
```

## Tailscale exposure

On the Mac (already in your tailnet):

```bash
# Run uvicorn on localhost:8000 (the default), then:
sudo tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:8000
tailscale serve status
```

`tailscale serve` automatically issues a `*.<tailnet>.ts.net` certificate, so
your iPhone (also on the tailnet) can reach `https://<host>.<tailnet>.ts.net`
without any extra config.

## Subscribing in Apple Podcasts (iPhone)

1. Make sure Tailscale is installed and running on the iPhone.
2. Upload a book in the web UI, click **Generate audio**, and wait for the first
   chapter to finish (you'll see "done" next to it).
3. On the book page, copy the feed URL (looks like
   `https://<host>.<tailnet>.ts.net/feed/<token>`).
4. Open Apple Podcasts → **Library** → tap the **⋯** menu top-right → **"Add a
   Show by URL"** → paste the feed → confirm.
5. New chapters appear automatically as the worker finishes them.

## Architecture

```
FastAPI (uvicorn) <-> SQLite <-> Worker (python -m bookcast.worker)
                              \-> ./data/{originals,chunks,chapters,covers}
```

- **Web**: FastAPI + Jinja + HTMX (server-rendered, no SPA build).
- **Worker**: standalone `python -m bookcast.worker` polls a `jobs` table.
  Crashes are recoverable: chunk-level WAVs persist on disk, and orphaned
  `running` jobs are reclaimed at worker startup.
- **TTS**: synthesizers are lazy-loaded; first request downloads weights (Kokoro
  to `~/.cache/huggingface`, Silero to `./data/models`).
- **RSS**: generated on-the-fly from DB state, with `ETag`/`Last-Modified` keyed
  on the latest done chapter.

## Known limits / next up

- Russian-only Silero voices for v1; Ukrainian falls back to Russian.
- `txt` chapter detection is heuristic — preview before generating, use the
  per-chapter "skip" toggle if it gets a heading wrong.
- One feed per book ⇒ one Apple Podcasts subscription per book. A combined
  "all books" feed (book = season) is planned.
