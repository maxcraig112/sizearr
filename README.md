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
- Rescans automatically once an hour in the background, with a manual
  "Rescan now" button if you don't want to wait.

## Running it

### With Docker (recommended)

Add this to your existing `docker-compose.yml`:

```yaml
services:
  media-size-browser:
    build: ./media-size-browser
    container_name: media-size-browser
    ports:
      - "5432:5432"
    volumes:
      - /path/to/your/movies:/media/movies:ro
      - /path/to/your/tv:/media/tv:ro
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
    volumes:
      - /path/to/your/movies:/media/movies:ro
      - /path/to/your/tv:/media/tv:ro
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
pip install -r requirements.txt
python app.py
```

By default it looks for media under `/media/movies` and `/media/tv`. Change
`MEDIA_ROOTS` in `app.py` if your paths are different, or mount your real
directories to those paths if running in a container.

## Configuration

| Variable                    | Default | Description                                   |
|------------------------------|---------|------------------------------------------------|
| `PORT`                        | `5432`  | Port the web server listens on                |
| `REFRESH_INTERVAL_SECONDS`    | `3600`  | How often to automatically rescan, in seconds |

## Project layout

```
.
├── app.py               # Flask app: scanning logic and API routes
├── templates/
│   └── index.html       # Frontend table (DataTables for sort/filter)
├── requirements.txt
├── Dockerfile
└── .github/
    └── workflows/
        └── deploy.yml   # Builds and pushes the image on every push to main
```
