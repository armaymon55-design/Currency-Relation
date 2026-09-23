"""Dashboard server (Tab 1). Serves the page and two JSON endpoints from the step-1
outputs and the bar cache. Run:  python app/server.py  ->  http://127.0.0.1:5050
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone  # noqa: E402

from config import DEFAULT_WINDOW, REFRESH_MINUTES, STALE_MINUTES, TIMEFRAMES, WINDOWS  # noqa: E402
from src.engine.store import INDEX_ORDER, DataStore  # noqa: E402
from src.pipeline import read_heartbeat  # noqa: E402


def create_app(store: DataStore | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(ROOT / "app" / "templates"),
                static_folder=str(ROOT / "app" / "static"))
    app.config["STORE"] = store
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    def get_store() -> DataStore:
        if app.config["STORE"] is None:
            app.config["STORE"] = DataStore.from_disk()
        app.config["STORE"].maybe_reload()
        return app.config["STORE"]

    def params():
        tf = request.args.get("tf", "H1")
        try:
            window = int(request.args.get("window", DEFAULT_WINDOW))
        except ValueError:
            abort(400, "window must be an integer")
        if tf not in TIMEFRAMES or window not in WINDOWS:
            abort(400, f"tf must be one of {TIMEFRAMES}, window one of {WINDOWS}")
        return tf, window

    @app.get("/")
    def index():
        return render_template("index.html", timeframes=TIMEFRAMES, windows=WINDOWS, default_window=DEFAULT_WINDOW)

    @app.get("/api/summary")
    def summary():
        tf, window = params()
        return jsonify(get_store().summary(tf, window))

    @app.get("/public/")
    @app.get("/public/<path:filename>")
    def public_site(filename: str = "index.html"):
        """Local preview of the static public build (public/site), as Vercel would serve it."""
        return send_from_directory(str(ROOT / "public" / "site"), filename)

    @app.get("/api/status")
    def status():
        """Heartbeat of the live updater + which snapshot the server is serving."""
        store = get_store()
        return jsonify({
            "heartbeat": read_heartbeat(),
            "snapshot": store._mtime,
            "generated": store.generated,
            "server_time_utc": datetime.now(timezone.utc).isoformat(),
            "refresh_minutes": REFRESH_MINUTES,
            "stale_minutes": STALE_MINUTES,
        })

    @app.get("/api/whatif")
    def whatif():
        tf, window = params()
        index = request.args.get("index", "DXY")
        try:
            move = float(request.args.get("move", 1.0))
        except ValueError:
            abort(400, "move must be a number")
        if index not in INDEX_ORDER:
            abort(404, "unknown index")
        if not -25 <= move <= 25:
            abort(400, "move must be between -25% and +25%")
        return jsonify(get_store().whatif(index, move, tf, window))

    @app.get("/api/map")
    def currency_map():
        tf, window = params()
        return jsonify(get_store().map_data(tf, window))

    @app.get("/api/pair/<pair>")
    def pair(pair: str):
        tf, window = params()
        index = request.args.get("index", "DXY")
        store = get_store()
        if index not in INDEX_ORDER or pair not in {s.name for s in store.sources}:
            abort(404, "unknown pair or index")
        return jsonify(store.pair_detail(pair, index, tf, window))

    return app


if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", "5050"))
    warm = DataStore.from_disk()
    for _tf in TIMEFRAMES:          # build the indices up front so the first page load is instant
        warm.indices(_tf)
    application = create_app(warm)
    try:
        from waitress import serve  # production WSGI server: stable keep-alive, multi-threaded
        print(f"Serving on http://127.0.0.1:{port} (waitress)", flush=True)
        serve(application, host="127.0.0.1", port=port, threads=6)
    except ImportError:             # fallback: Flask's development server
        application.run(host="127.0.0.1", port=port, debug=False)
