"""Entrypoint. The app itself lives in the `sizearr` package; this file just
starts it so `python app.py` and the Docker CMD keep working. WSGI servers can
still import `app:app`."""
from sizearr.web import app, run

if __name__ == "__main__":
    run()
