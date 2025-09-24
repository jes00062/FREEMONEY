import requests
from datetime import datetime, timezone

# 🔑 Your Odds API Key
API_KEY = "f7aa230a8379043a6fee01e111290300"

# 🎯 Config
SPORT = "americanfootball_nfl"
ALLOWED_BOOK_KEYS = ["draftkings", "fanduel", "betmgm", "betrivers", "bovada"]
PLAYER_PROP_MARKETS = [
    "player_pass_yds",
    "player_rush_yds",
    "player_receptions",
    "player_rush_tds",
    "player_pass_tds",
    "player_anytime_td"
]

# 🎲 Helper functions
def decimal_to_american(decimal_odds):
    if decimal_odds >= 2.0:
        return f"+{int((decimal_odds - 1) * 100)}"
    else:
        return f"-{int(100 / (decimal_odds - 1))}"

def calculate_arbitrage(odds1, odds2):
    inv_sum = (1 / odds1) + (1 / odds2)
    if inv_sum < 1:
        margin = (1 - inv_sum) * 100
        stake1 = round((1 / odds1) / inv_sum * 1000, 2)
        stake2 = round((1 / odds2) / inv_sum * 1000, 2)
        profit = round((min(stake1 * odds1, stake2 * odds2) - 1000), 2)
        return margin, stake1, stake2, profit
    return None

def fetch_events():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/?apiKey={API_KEY}"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

def fetch_event_props(event_id):
    url = (
        f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"
        f"?apiKey={API_KEY}&regions=us&markets={','.join(PLAYER_PROP_MARKETS)}"
        f"&oddsFormat=decimal&bookmakers={','.join(ALLOWED_BOOK_KEYS)}"
    )
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

# 🚀 Main logic
def main():
    print("✅ Starting player props arbitrage scan...\n")

    events = fetch_events()
    print(f"Fetched {len(events)} {SPORT} events.\n")

    for event in events:
        home, away = event["home_team"], event["away_team"]
        event_id = event["id"]
        print(f"📅 {away} vs {home}")

        try:
            data = fetch_event_props(event_id)
        except Exception as e:
            print(f"   ❌ Error fetching props: {e}")
            continue

        bookmakers = data.get("bookmakers", [])
        for market in data.get("markets", []):
            market_key = market["key"]
            outcomes_by_book = {}

            for book in bookmakers:
                book_key = book["key"]
                if book_key not in ALLOWED_BOOK_KEYS:
                    continue
                for bm_market in book["markets"]:
                    if bm_market["key"] == market_key:
                        for outcome in bm_market["outcomes"]:
                            name = outcome["description"]
                            price = outcome["price"]
                            last_update = outcome.get("last_update")
                            outcomes_by_book.setdefault(name, []).append(
                                (book_key, price, last_update)
                            )

            for player, offers in outcomes_by_book.items():
                if len(offers) < 2:
                    continue
                best = sorted(offers, key=lambda x: -x[1])[:2]
                arb = calculate_arbitrage(best[0][1], best[1][1])
                if arb:
                    margin, stake1, stake2, profit = arb
                    print(f"   🎯 {market_key} → {player}")
                    for book_key, price, last_update in best:
                        update_time = datetime.fromisoformat(
                            last_update.replace("Z", "+00:00")
                        ) if last_update else None
                        freshness = (
                            f"{(datetime.now(timezone.utc) - update_time).seconds//60}m old"
                            if update_time else "unknown"
                        )
                        print(
                            f"      {book_key} → {decimal_to_american(price)} "
                            f"(dec {price:.2f}) | ⏱ {freshness}"
                        )
                    print(
                        f"      ✅ Margin: {margin:.2f}% | "
                        f"Suggested: {best[0][0]} ${stake1}, {best[1][0]} ${stake2} "
                        f"| Profit: ${profit}\n"
                    )

if __name__ == "__main__":
    main()
