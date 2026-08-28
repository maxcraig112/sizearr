# Media Size Browser

A small web app that scans your movies and TV folders and shows every title
in a single sortable, filterable table, so you can quickly see what's taking
up the most space on disk.

## What it does

- Walks two directories you point it at (movies and TV), treating each
  top-level folder as one title.
- Computes the total size of each title, including everything nested inside
  it (extras, subtitles, multiple episodes, etc).
- Serves a web page with a sortable table. Click "Size" to sort largest to
  smallest, filter by category, or search by title.
- Groups TV by show; click a show row to expand a size-descending breakdown
  of every file it contains (episodes, subtitles, extras).
- Rescans automatically once an hour in the background, with a manual
  "Rescan now" button if you don't want to wait.
- Logs every step of each scan to stdout (`docker logs -f media-size-browser`),
  so you can see which folders it's walking, anything it can't read, and how
  long the scan took. Front-end assets (jQuery / DataTables) are bundled under
  `static/vendor/`, so it works with no internet access.

## Running it

### With Docker (recommended)

Add this to your existing `docker-compose.yml`. Set `MOVIES_PATH` and
`TV_PATH` to wherever the libraries live *inside the container*, and mount
your real directories accordingly:

```yaml
services:
  media-size-browser:
    build: ./media-size-browser
    container_name: media-size-browser
    ports:
      - "5432:5432"
    environment:
      - MOVIES_PATH=/media/movies
      - TV_PATH=/media/tv
    volumes:
      # One media root, with movies/ and tv/ inside it:
      - /path/to/your/media:/media:ro
      # ...or mount the two libraries separately:
      # - /path/to/your/movies:/media/movies:ro
      # - /path/to/your/tv:/media/tv:ro
    restart: unless-stopped
```

Then:

```bash
docker compose up -d --build media-size-browser
```

Visit `http://<your-server-ip>:5432/`.

### Using the published image

Every push to `main` builds the image and publishes it to Docker Hub, so you
don't have to build it yourself on the server. Once that's run at least
once, you can point `docker-compose.yml` at the image instead:

```yaml
services:
  media-size-browser:
    image: maximiliancraig112/media-size-browser:latest
    container_name: media-size-browser
    ports:
      - "5432:5432"
    environment:
      - MOVIES_PATH=/media/movies
      - TV_PATH=/media/tv
    volumes:
      - /path/to/your/media:/media:ro
    restart: unless-stopped
```

```bash
docker compose pull media-size-browser
docker compose up -d media-size-browser
```

The workflow needs two repository secrets to push to Docker Hub. In your
GitHub repo, go to Settings → Secrets and variables → Actions, and add:

| Secret               | Value                                                             |
|-----------------------|--------------------------------------------------------------------|
| `DOCKERHUB_USERNAME`  | `maximiliancraig112`                                              |
| `DOCKERHUB_TOKEN`     | An access token from Docker Hub (Account Settings → Security → New Access Token), not your password |

### Without Docker

```bash
make install       # or: pip install -r requirements.txt
make run-local     # run against the bundled testdata/ fixture library
make run           # run against MOVIES_PATH / TV_PATH from the environment

# point it at a real library
MOVIES_PATH=/data/movies TV_PATH=/data/tv make run
```

By default it looks for media under `/media/movies` and `/media/tv`. Set
`MOVIES_PATH` and `TV_PATH` to point it somewhere else, or mount your real
directories to those paths if running in a container.

`make run-local` uses `testdata/` — a small library of empty placeholder
files (see [`testdata/README.md`](testdata/README.md)) so you can see the UI
working without a real media library.

## Configuration

| Variable                    | Default         | Description                                   |
|------------------------------|-----------------|-----------------------------------------------|
| `MOVIES_PATH`                 | `/media/movies` | Directory scanned for movie titles           |
| `TV_PATH`                     | `/media/tv`     | Directory scanned for TV titles              |
| `PORT`                        | `5432`          | Port the web server listens on               |
| `REFRESH_INTERVAL_SECONDS`    | `3600`          | How often to automatically rescan, in seconds |
| `LOG_LEVEL`                   | `INFO`          | `DEBUG` adds a log line per title with its size |

## Project layout

```
.
├── app.py                 # Flask app: scanning logic, logging, API routes
├── templates/
│   └── index.html         # Page markup only
├── static/
│   ├── css/
│   │   ├── base.css       # Design tokens, reset, document defaults
│   │   ├── layout.css     # Page scaffold: column, header, stats grid, toolbar
│   │   ├── components.css # Stat cards, filters, buttons, pills, status
│   │   └── table.css      # DataTables theme + size-bar cell
│   ├── js/
│   │   └── app.js         # Fetches /api/media and renders the table
│   └── vendor/            # Bundled jQuery + DataTables (no CDN needed)
├── testdata/              # Empty placeholder library for `make run-local`
├── requirements.txt
├── Makefile               # `make install` / `make run` / `make run-local`
├── Dockerfile
└── .github/
    └── workflows/
        └── deploy.yml     # Builds and pushes the image on every push to main
```
