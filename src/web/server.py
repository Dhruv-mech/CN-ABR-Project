"""Flask HTTP Server for MPEG-DASH Video Streaming.

Serves the MPEG-DASH manifest (.mpd), initialization segments, and media chunks (.m4s)
locally to web browsers and video players (such as dash.js).

Key Features:
- Resolves all DASH asset paths relative to the project root, independent of terminal working directory.
- Strictly guards against directory traversal attacks, restricting requests to the designated DASH directory.
- Serves '.mpd' with standard 'application/dash+xml' MIME type.
- Serves '.m4s' ISO BMFF segments with 'video/mp4' MIME type (compliant with W3C Media Source Extensions).
- Exposes a health endpoint ('/health') returning JSON status and asset inventory.
- Provides CORS headers allowing browser clients to fetch streams without cross-origin blocks.
- Binds to 127.0.0.1 by default with configurable port (default: 5000) and debug mode disabled.
"""

import argparse
import datetime
import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path
from typing import Optional, Union, Dict, Any, List

from flask import Flask, Response, jsonify, request, send_file, render_template

# Resolve project root (D:\CN-ABR-Project)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DASH_DIR = PROJECT_ROOT / "static" / "dash"
DEFAULT_TEMPLATE_DIR = PROJECT_ROOT / "templates"
DEFAULT_STATIC_DIR = PROJECT_ROOT / "static"
DEFAULT_EXPERIMENTS_FILE = PROJECT_ROOT / "results" / "browser_experiments.json"

# Ensure custom MPEG-DASH MIME types are registered in Python's mimetypes database
mimetypes.add_type("application/dash+xml", ".mpd")
mimetypes.add_type("video/mp4", ".m4s")


def get_mimetype_for_file(filename: str) -> str:
    """
    Determines the appropriate MIME type for DASH streaming artifacts.

    Note on .m4s segments:
    In MPEG-DASH (ISO/IEC 23009-1), both video and audio tracks are packaged as
    ISO Base Media File Format (ISO BMFF) fragments ending in .m4s. Modern web
    browsers (Chromium, Firefox, Safari) and dash.js require these segments to be
    served with a valid container MIME type such as 'video/mp4' (or 'audio/mp4')
    for MediaSource buffer appending. We standardize on 'video/mp4' for all .m4s files.
    """
    name_lower = filename.lower()
    if name_lower.endswith(".mpd"):
        return "application/dash+xml"
    if name_lower.endswith(".m4s") or name_lower.endswith(".mp4"):
        return "video/mp4"
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def load_experiments_data(file_path: Path) -> List[Dict[str, Any]]:
    """Loads saved experiment records from disk."""
    if not file_path.is_file():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_experiments_data(file_path: Path, data: List[Dict[str, Any]]) -> None:
    """Safely saves experiment records to disk with atomic replacement."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    temp_path.replace(file_path)


def create_app(
    dash_dir: Optional[Union[str, Path]] = None,
    template_folder: Optional[Union[str, Path]] = None,
    static_folder: Optional[Union[str, Path]] = None,
    experiments_file: Optional[Union[str, Path]] = None,
) -> Flask:
    """
    Application factory for the DASH streaming server.

    Args:
        dash_dir: Path to directory containing DASH stream artifacts (defaults to static/dash).
        template_folder: Path to directory containing HTML templates (defaults to templates/).
        static_folder: Path to directory containing static assets (defaults to static/).
        experiments_file: Path to JSON file for browser experiment persistence.

    Returns:
        Flask: Configured Flask application instance.
    """
    tmpl_dir = Path(template_folder).resolve() if template_folder else DEFAULT_TEMPLATE_DIR.resolve()
    stat_dir = Path(static_folder).resolve() if static_folder else DEFAULT_STATIC_DIR.resolve()

    app = Flask(
        __name__,
        template_folder=str(tmpl_dir),
        static_folder=str(stat_dir),
        static_url_path="/static",
    )

    # Configure DASH storage directory
    resolved_dash_dir = Path(dash_dir).resolve() if dash_dir else DEFAULT_DASH_DIR.resolve()
    app.config["DASH_DIR"] = resolved_dash_dir

    # Configure Experiments persistence file
    resolved_exp_file = Path(experiments_file).resolve() if experiments_file else DEFAULT_EXPERIMENTS_FILE.resolve()
    app.config["EXPERIMENTS_FILE"] = resolved_exp_file

    @app.after_request
    def add_cors_headers(response: Response) -> Response:
        """Adds CORS and Range headers allowing external web players to consume the stream."""
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, HEAD, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Range, Accept-Encoding, Content-Type"
        response.headers["Access-Control-Expose-Headers"] = "Content-Length, Content-Range, Accept-Ranges"
        return response

    @app.route("/health", methods=["GET"])
    def health_check():
        """
        Health endpoint reporting server status and DASH asset availability.

        Returns:
            JSON object detailing manifest existence and chunk inventory.
        """
        current_dash_dir: Path = app.config["DASH_DIR"]
        manifest_file = current_dash_dir / "stream.mpd"
        manifest_exists = manifest_file.is_file()

        init_chunks = list(current_dash_dir.glob("init-stream*.m4s")) if current_dash_dir.is_dir() else []
        media_chunks = list(current_dash_dir.glob("chunk-stream*.m4s")) if current_dash_dir.is_dir() else []

        payload: Dict[str, Any] = {
            "status": "healthy" if manifest_exists else "degraded",
            "manifest_exists": manifest_exists,
            "manifest_name": "stream.mpd",
            "dash_dir": str(current_dash_dir),
            "init_segments_count": len(init_chunks),
            "media_segments_count": len(media_chunks),
            "message": (
                "DASH stream is ready for playback."
                if manifest_exists
                else "DASH manifest not found. Run 'py -m src.media.encode_dash' to encode the stream."
            ),
        }
        return jsonify(payload), 200

    def serve_dash_file(filename: str):
        """Internal helper to safely serve DASH files from configured directory."""
        current_dash_dir: Path = app.config["DASH_DIR"]

        # Prevent empty or whitespace paths
        clean_name = filename.strip()
        if not clean_name:
            return jsonify({"error": "No filename specified"}), 400

        # Safe path resolution strictly within current_dash_dir
        try:
            target_path = (current_dash_dir / clean_name).resolve()
        except Exception:
            return jsonify({"error": "Invalid path specified"}), 400

        # Enforce directory boundary check (Defense against Path Traversal: ../../)
        try:
            target_path.relative_to(current_dash_dir)
        except ValueError:
            return jsonify({
                "error": "Access forbidden: directory traversal attempt detected",
                "requested_path": clean_name,
            }), 403

        # Check file existence
        if not target_path.is_file():
            if target_path.name.lower().endswith(".mpd"):
                return jsonify({
                    "error": f"DASH manifest '{target_path.name}' not found on server.",
                    "hint": "Run 'py -m src.media.encode_dash' from project root to encode media/input.mp4 first.",
                    "expected_path": str(target_path),
                }), 404
            return jsonify({
                "error": f"Media file '{target_path.name}' not found.",
                "dash_directory": str(current_dash_dir),
            }), 404

        # Determine appropriate MIME type
        mimetype = get_mimetype_for_file(target_path.name)

        # send_file with conditional=True supports HTTP 206 Partial Content (Range requests)
        return send_file(
            target_path,
            mimetype=mimetype,
            as_attachment=False,
            conditional=True,
        )

    # Route 1: Direct DASH path (/dash/stream.mpd, /dash/chunk-stream0-00001.m4s)
    @app.route("/dash/<path:filename>", methods=["GET"])
    def get_dash_file(filename: str):
        return serve_dash_file(filename)

    # Route 2: Static DASH path alias (/static/dash/stream.mpd)
    @app.route("/static/dash/<path:filename>", methods=["GET"])
    def get_static_dash_file(filename: str):
        return serve_dash_file(filename)

    # Route 3: Interactive MPEG-DASH Web Player (Stage 8B)
    @app.route("/player", methods=["GET"])
    def player_page():
        """Serves the interactive MPEG-DASH web streaming player."""
        return render_template("player.html", manifest_url="/dash/stream.mpd")

    # Route 4: Root index (directs to player)
    @app.route("/", methods=["GET"])
    def index():
        """Root endpoint presenting the video streaming dashboard."""
        return render_template("player.html", manifest_url="/dash/stream.mpd")

    # Route 5: Experiments API (Stage 12 / ABR Comparison Dashboard)
    @app.route("/api/experiments", methods=["GET"])
    def get_experiments():
        """Returns JSON list of saved browser ABR experiment comparison runs."""
        exp_file: Path = app.config["EXPERIMENTS_FILE"]
        data = load_experiments_data(exp_file)
        return jsonify(data), 200

    @app.route("/api/experiments", methods=["POST"])
    def add_experiment():
        """Saves a completed browser ABR experiment run summary for persistent comparison."""
        payload = request.get_json(silent=True)
        if not payload or not isinstance(payload, dict):
            return jsonify({"error": "Invalid or missing JSON payload"}), 400

        exp_file: Path = app.config["EXPERIMENTS_FILE"]
        experiments = load_experiments_data(exp_file)

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        exp_id = payload.get("id") or f"exp-{int(datetime.datetime.now().timestamp() * 1000)}"

        record: Dict[str, Any] = {
            "id": str(exp_id),
            "algorithm": str(payload.get("algorithm", "unknown")),
            "algorithmName": str(payload.get("algorithmName", payload.get("algorithm", "Unknown"))),
            "networkScenario": str(payload.get("networkScenario", "Default")),
            "startTime": payload.get("startTime", now_iso),
            "endTime": payload.get("endTime", now_iso),
            "durationSec": float(payload.get("durationSec", 0.0)),
            "avgBitrateKbps": float(payload.get("avgBitrateKbps", 0.0)),
            "avgThroughputKbps": float(payload.get("avgThroughputKbps", 0.0)),
            "avgBufferSec": float(payload.get("avgBufferSec", 0.0)),
            "switchCount": int(payload.get("switchCount", 0)),
            "stallCount": int(payload.get("stallCount", 0)),
            "totalRebufferSec": float(payload.get("totalRebufferSec", 0.0)),
            "rebufferRatio": float(payload.get("rebufferRatio", 0.0)),
            "avgDownloadTimeSec": float(payload.get("avgDownloadTimeSec", 0.0)),
            "qoeScore": float(payload.get("qoeScore", 0.0)),
            "timestamp": payload.get("timestamp", now_iso),
        }

        experiments.append(record)
        save_experiments_data(exp_file, experiments)
        return jsonify({"status": "success", "experiment": record}), 201

    @app.route("/api/experiments", methods=["DELETE"])
    def clear_experiments():
        """Clears all saved browser ABR experiment comparison runs."""
        exp_file: Path = app.config["EXPERIMENTS_FILE"]
        save_experiments_data(exp_file, [])
        return jsonify({"status": "cleared", "experiments": []}), 200

    return app


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments for the Flask server."""
    parser = argparse.ArgumentParser(
        description="Local Flask HTTP Server for MPEG-DASH Video Streaming.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-H", "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind HTTP server.",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=5000,
        help="Port number to listen on.",
    )
    parser.add_argument(
        "-d", "--dash-dir",
        type=str,
        default=None,
        help="Custom path to directory containing DASH files (defaults to static/dash).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (disabled by default).",
    )
    return parser.parse_args()


def run_server(
    host: str = "127.0.0.1",
    port: int = 5000,
    dash_dir: Optional[Union[str, Path]] = None,
    debug: bool = False,
) -> None:
    """
    Initializes and starts the Flask HTTP server.

    Args:
        host: Host address (default: 127.0.0.1).
        port: Listening port (default: 5000).
        dash_dir: Optional custom DASH storage directory.
        debug: Whether to enable Flask debug reloader (default: False).
    """
    app = create_app(dash_dir=dash_dir)
    storage_dir = app.config["DASH_DIR"]
    manifest_file = storage_dir / "stream.mpd"

    print("\n" + "=" * 62)
    print("           MPEG-DASH LOCAL HTTP STREAMING SERVER")
    print("=" * 62)
    print(f"  Bound Address     : http://{host}:{port}")
    print(f"  Web Player URL    : http://{host}:{port}/player")
    print(f"  Health Check URL  : http://{host}:{port}/health")
    print(f"  DASH Manifest URL : http://{host}:{port}/dash/stream.mpd")
    print(f"  Manifest Status   : {'FOUND (Ready)' if manifest_file.is_file() else 'MISSING (Encode video first)'}")
    print("-" * 62)
    print("Press CTRL+C to stop the server.\n")

    app.run(host=host, port=port, debug=debug)


def main() -> int:
    """Main CLI entry point."""
    args = parse_args()
    try:
        run_server(
            host=args.host,
            port=args.port,
            dash_dir=args.dash_dir,
            debug=args.debug,
        )
        return 0
    except KeyboardInterrupt:
        print("\nServer stopped by user.")
        return 0
    except Exception as e:
        print(f"\nServer error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
