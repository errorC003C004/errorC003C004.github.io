import re
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup
import os
import time
import uuid
from urllib.parse import urlparse
from flask import send_file, abort

app = Flask(__name__)

TOP_URL = "https://steamcharts.com/top"
STEAM_SUGGEST_URL = "https://store.steampowered.com/search/suggest/"
APP_RE = re.compile(r"^/app/(\d+)$")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://walftech.com/gamelist/index.html'
}


TEMP_DIR = "temp_downloads"
MAX_AGE = 30 * 60
MAX_FILE_SIZE = 1024 * 1024 * 500  # 500 MB

os.makedirs(TEMP_DIR, exist_ok=True)

download_hosts = {
    "steamgames554.s3.us-east-1.amazonaws.com",
}

def cleanup_old_files():
    now = time.time()

    for name in os.listdir(TEMP_DIR):
        path = os.path.join(TEMP_DIR, name)

        if os.path.isfile(path) and now - os.path.getmtime(path) > MAX_AGE:
            try:
                os.remove(path)
            except OSError:
                pass


def is_allowed_url(url):
    parsed = urlparse(url)

    return (
        parsed.scheme in ("http", "https")
        and parsed.netloc in download_hosts
        and parsed.path.endswith(".zip")
    )

@app.route("/download")
def download_zip():
    cleanup_old_files()

    file_url = request.args.get("url", "").strip()

    if not file_url:
        abort(400, "Missing download URL")

    if not is_allowed_url(file_url):
        abort(403, "Download URL is not allowed")

    filename = f"{uuid.uuid4()}.zip"
    file_path = os.path.join(TEMP_DIR, filename)

    try:
        with requests.get(file_url, headers=HEADERS, stream=True, timeout=60) as response:
            response.raise_for_status()

            total = 0

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue

                    total += len(chunk)

                    if total > MAX_FILE_SIZE:
                        f.close()
                        os.remove(file_path)
                        abort(413, "File is too large")

                    f.write(chunk)

    except requests.RequestException:
        if os.path.exists(file_path):
            os.remove(file_path)

        abort(400, "Failed to download file")

    return send_file(
        file_path,
        as_attachment=True,
        download_name=os.path.basename(urlparse(file_url).path) or "download.zip",
        mimetype="application/zip"
    )


def get_top_games(limit=100):
    response = requests.get(TOP_URL, headers=HEADERS, stream=True, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    games = []
    rows = soup.select("table tbody tr")

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        link = cols[1].find("a", href=True)
        if not link:
            continue

        href = link["href"].strip()
        match = APP_RE.match(href)
        if not match:
            continue

        app_id = int(match.group(1))
        name = link.get_text(strip=True)
        players_text = cols[2].get_text(strip=True)

        games.append({
            "name": name,
            "app_id": app_id,
            "players_text": f"{players_text} playing",
            "store_url": f"https://steamgames554.s3.us-east-1.amazonaws.com/{app_id}.zip",
            "banner_url": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"
        })

        if len(games) >= limit:
            break

    return games


def get_steam_suggestions(query, limit=8):
    params = {
        "term": query,
        "f": "json",
        "cc": "US",
        "l": "english",
        "realm": "1"
    }

    response = requests.get(STEAM_SUGGEST_URL, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()

    results = []
    seen = set()

    for item in data[:limit]:
        app_id = item.get("id")
        name = (item.get("name") or "").strip()

        if not app_id or not name or app_id in seen:
            continue

        seen.add(app_id)
        results.append({
            "name": name,
            "app_id": int(app_id),
            "store_url": f"https://steamgames554.s3.us-east-1.amazonaws.com/{app_id}.zip",
            "banner_url": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
            "players_text": "Steam result"
        })

    return results


@app.route("/")
def index():
    try:
        games = get_top_games(100)
        error = None
    except Exception as e:
        games = []
        error = str(e)

    return render_template("index.html", games=games, error=error)


@app.route("/top-games")
def top_games():
    try:
        return jsonify({"games": get_top_games(100)})
    except Exception as e:
        return jsonify({"games": [], "error": str(e)}), 500


@app.route("/suggest")
def suggest():
    q = request.args.get("q", "").strip()

    if not q:
        return jsonify({"games": []})

    try:
        games = get_steam_suggestions(q, limit=8)

        # Also filter by ID locally if the user typed numbers
        q_lower = q.lower()
        filtered = [
            g for g in games
            if q_lower in g["name"].lower() or q_lower in str(g["app_id"])
        ]

        return jsonify({"games": filtered})
    except Exception as e:
        return jsonify({"games": [], "error": str(e)}), 500


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()

    if not q:
        try:
            return jsonify({"count": 0, "games": []})
        except Exception as e:
            return jsonify({"count": 0, "games": [], "error": str(e)}), 500

    try:
        games = get_steam_suggestions(q, limit=20)

        q_lower = q.lower()
        filtered = [
            g for g in games
            if q_lower in g["name"].lower() or q_lower in str(g["app_id"])
        ]

        return jsonify({
            "count": len(filtered),
            "games": filtered
        })
    except Exception as e:
        return jsonify({
            "count": 0,
            "games": [],
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
