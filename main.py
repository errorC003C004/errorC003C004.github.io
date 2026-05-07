import re
from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

TOP_URL = "https://steamcharts.com/top"
STEAM_SUGGEST_URL = "https://store.steampowered.com/search/suggest/"
APP_RE = re.compile(r"^/app/(\d+)$")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://walftech.com/gamelist/index.html'
}

cookies = {"cf_clearance": "TBz8H5F7aZkebt0jj_wJkx6clzKrAW3oFTqJOrG0Z3E-1778112433-1.2.1.1-keoi1ajJHl_DetcqYNUA7I2kNHc0P6E1Mf_N5sB3qI.uMIYHHVY5rcZ6a.KYKZy5N9gl6GT0swZ3Gza4GfA3Zds.yBYDU_NnAZ3hFvjQhK3lZiFa8mcSju.kqQpUz0l8WyxRqiCcEFnrG.l3MRa.CTTVbw2rlKgTYvBgpI9wlly9BFhziPedGJDN8uD4HPDjJ8XyuBBi5YSWYSV6hy1wj24nDqrLJ43ocE6HQAR.j4SNEy2aFQlqykZs8oNzcVzT_agBY4.pMW_TOamwww2OQOih.bgQP6zWdjHqXWxJr_elddU486Jp7Bd13HjOD2XOS66sYx5k_P_qLFyRWRf_7Q"}



def get_top_games(limit=100):
    response = requests.get(TOP_URL, cookies=cookies, headers=HEADERS, stream=True, timeout=30)
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
