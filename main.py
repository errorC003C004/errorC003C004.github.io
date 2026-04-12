import re
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

TOP_URL = "https://steamcharts.com/top"
STEAM_SUGGEST_URL = "https://store.steampowered.com/search/suggest/"
APP_RE = re.compile(r"^/app/(\d+)$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
}


def get_top_games(limit=100):
    response = requests.get(TOP_URL, headers=HEADERS, timeout=30)
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