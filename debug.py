# debug_markets_complete.py
import os
import requests
from datetime import datetime
import sys
import json

# -------------- CONFIG --------------
# Option A (secure): set ODDS_API_KEY in your shell:
#   export ODDS_API_KEY="your_real_key_here"
# Option B (quick): paste your key here (NOT recommended for long-term)
API_KEY = ("f7aa230a8379043a6fee01e111290300") 
# API_KEY = "paste-your-key-here"   # <-- uncomment only if you want to hardcode

SPORT = "baseball_mlb"
REGION = "us"
MARKET = "h2h"
ODDS_FORMAT = "american"
TIMEOUT = 15

if not API_KEY:
    print("❌ No API key found. Set environment variable ODDS_API_KEY or paste your key in the script.")
    print("   Example (mac/linux): export ODDS_API_KEY='your_key_here'")
    sys.exit(1)

def fetch_odds():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": MARKET,
        "oddsFormat": ODDS_FORMAT,
        "dateFormat": "iso"
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
    except Exception as e:
        print("❌ Network/fetch error:", e)
        return None, None

    # Helpful debug if unauthorized or other error
    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code} returned from API.")
        # print a chunk of the response body for debugging (may contain JSON error)
        text = resp.text
        snippet = text[:1000] + ("..." if len(text) > 1000 else "")
        print("   Response body (first 1000 chars):")
        print(snippet)
        return resp.status_code, None

    try:
        data = resp.json()
    except Exception as e:
        print("❌ Failed to decode JSON:", e)
        print("   Raw response (first 1000 chars):")
        print(resp.text[:1000])
        return resp.status_code, None

    return resp.status_code, data

status, games = fetch_odds()
if status != 200:
    print("\n➡️ Most common causes: invalid API key (401), expired/over quota, or bad request params.")
    print("Check your ODDS_API_KEY and remaining credits with the dashboard.")
    sys.exit(1)

if not games:
    print("⚠️ No games returned in response.")
    sys.exit(0)

# Print the first game with full market detail
game = games[0]
home = game.get("home_team")
away = game.get("away_team")
start = game.get("commence_time")
try:
    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    nice_time = dt.strftime("%b %d, %Y @ %I:%M %p")
except Exception:
    nice_time = start

print(f"\n🔎 Inspecting first game: {away} vs {home}")
print(f"📅 start: {nice_time}")
print(f"📦 Raw JSON for this game (pretty-printed, limited):\n")

# show markets and outcomes grouped by bookmaker
for bookmaker in game.get("bookmakers", []):
    book_title = bookmaker.get("title")
    print(f"\n📖 Bookmaker: {book_title}")
    # show top-level fields in bookmaker
    kb = {k: v for k, v in bookmaker.items() if k != "markets"}
    print("   meta:", json.dumps(kb, default=str))
    for market in bookmaker.get("markets", []):
        mkey = market.get("key")
        mtype = market.get("outcomes", None) is not None
        print(f"   🎯 Market key: {mkey}  (has_outcomes: {bool(market.get('outcomes'))})")
        for outcome in market.get("outcomes", []):
            name = outcome.get("name")
            price = outcome.get("price")
            print(f"      - {name}  @ {price}")

print("\n✅ Done printing full market/outcome details for the first game.")
print("If you want, re-run but search for suspicious odds (e.g. abs(price) >= 2000) or inspect a specific bookmaker name.")
