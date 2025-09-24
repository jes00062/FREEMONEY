import requests
import pandas as pd
from datetime import datetime
import pytz
import sys

# ---------- CONFIG ----------
API_KEY = "f7aa230a8379043a6fee01e111290300"  # <-- Replace with your live key
REGION = "us"
UNIT_SIZE = 1000
TOP_N = 5
ROUND_TO = 5

SPORTS = ["baseball_mlb"]

SPORT_MARKETS = {
    "baseball_mlb": ["spreads", "totals"],
    "americanfootball_nfl": ["spreads", "totals"],
    "americanfootball_ncaaf": ["spreads", "totals"]
}

ALLOWED_BOOK_KEYS = None  # None allows all bookmakers
REQUEST_TIMEOUT = 10
# ----------------------------

def format_game_time(iso_time_str):
    utc_time = datetime.fromisoformat(iso_time_str.replace("Z", "+00:00"))
    eastern = pytz.timezone("US/Eastern")
    local_time = utc_time.astimezone(eastern)
    return local_time.strftime("%b %d, %Y @ %I:%M %p")

def american_to_decimal(odds):
    if odds > 0:
        return (odds / 100) + 1
    else:
        return (100 / abs(odds)) + 1

def format_american(odds):
    return f"+{int(odds)}" if odds > 0 else f"{int(odds)}"

def calculate_stakes(unit, dec_a, dec_b, round_to=ROUND_TO):
    stake_a = (unit / dec_a) / ((1/dec_a) + (1/dec_b))
    stake_b = (unit / dec_b) / ((1/dec_a) + (1/dec_b))
    stake_a = round(stake_a / round_to) * round_to
    stake_b = round(stake_b / round_to) * round_to
    payout_a = stake_a * dec_a
    payout_b = stake_b * dec_b
    guaranteed_payout = min(payout_a, payout_b)
    total_stake = stake_a + stake_b
    profit = guaranteed_payout - total_stake
    return stake_a, stake_b, profit

# ---------------------------
# Step 0: Check API status / credits
# ---------------------------
try:
    status_response = requests.get(
        "https://api.the-odds-api.com/v4/sports/",
        params={"apiKey": API_KEY},
        timeout=REQUEST_TIMEOUT
    )
    status_response.raise_for_status()
except requests.exceptions.HTTPError as e:
    if status_response.status_code == 401:
        print("❌ Unauthorized: Your API key is invalid or expired.")
    else:
        print(f"❌ HTTP Error: {e}")
    sys.exit(1)
except Exception as e:
    print("❌ Error contacting Odds API:", e)
    sys.exit(1)

remaining = status_response.headers.get("x-requests-remaining")
if remaining:
    print(f"✅ Remaining API credits: {remaining}")
else:
    print("⚠️ Could not detect remaining credits from API response headers.")

# ---------------------------
# Step 1: Fetch odds
# ---------------------------
rows = []
for sport in SPORTS:
    markets = SPORT_MARKETS.get(sport, ["spreads", "totals"])
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso"
    }

    print(f"Fetching {sport} ({', '.join(markets)}) ...")
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 401:
            print(f"❌ Unauthorized for {sport}: Invalid API key.")
        else:
            print(f"❌ Error fetching {sport}: {e}")
        continue
    except Exception as e:
        print(f"❌ Request error for {sport}: {e}")
        continue

    data = resp.json()
    if not data:
        print(f"⚠️ No games returned for {sport}")
        continue

    for game in data:
        home_team, away_team = game["home_team"], game["away_team"]
        commence_time = game["commence_time"]
        for book in game.get("bookmakers", []):
            if ALLOWED_BOOK_KEYS and book.get("key") not in ALLOWED_BOOK_KEYS:
                continue
            book_title = book.get("title")
            book_key = book.get("key")
            for market in book.get("markets", []):
                mkey = market.get("key")
                if mkey not in ("spreads", "totals"):
                    continue
                for outcome in market.get("outcomes", []):
                    rows.append({
                        "sport": sport,
                        "market": mkey,
                        "home_team": home_team,
                        "away_team": away_team,
                        "commence_time": commence_time,
                        "bookmaker": book_title,
                        "book_key": book_key,
                        "team": outcome.get("name"),
                        "line": outcome.get("point"),
                        "odds": outcome.get("price")
                    })

df = pd.DataFrame(rows)
if df.empty:
    print("⚠️ No odds data available after parsing. Check your API key or credits.")
    sys.exit(0)

df["odds"] = pd.to_numeric(df["odds"], errors="coerce")
df["line"] = pd.to_numeric(df["line"], errors="coerce")
df["line_abs"] = df["line"].abs().round(3)

print(f"✅ Parsed {len(df)} odds entries into the DataFrame.")

# ---------------------------
# Step 2: Find arbs
# ---------------------------
arb_list = []

for sport in SPORTS:
    for market in ("spreads", "totals"):
        sub = df[(df["sport"] == sport) & (df["market"] == market)]
        if sub.empty:
            continue

        group_cols = ["sport", "market", "line_abs", "home_team", "away_team", "commence_time"]
        groups = sub.groupby(group_cols, dropna=False)

        for (s, m, line_abs, home, away, start), group in groups:
            if pd.isna(line_abs):
                continue

            if m == "spreads":
                home_rows = group[group["team"] == home]
                away_rows = group[group["team"] == away]
                if home_rows.empty or away_rows.empty:
                    continue

                best_home = home_rows.sort_values("odds", ascending=False).iloc[0]
                best_away = away_rows.sort_values("odds", ascending=False).iloc[0]

                home_line = best_home["line"]
                away_line = best_away["line"]

                # ✅ Only take opposite spreads
                if home_line is None or away_line is None:
                    continue
                if home_line != -away_line:
                    continue

                dec_home = american_to_decimal(best_home["odds"])
                dec_away = american_to_decimal(best_away["odds"])
                arb_percent = (1/dec_home) + (1/dec_away)

                if arb_percent < 1:
                    profit_margin = (1 - arb_percent) * 100
                    stake_home, stake_away, profit = calculate_stakes(UNIT_SIZE, dec_home, dec_away)
                    arb_list.append({
                        "sport": sport,
                        "market": "Spread",
                        "line_value": line_abs,
                        "home_team": home,
                        "away_team": away,
                        "start_time": start,
                        "home_book": best_home["bookmaker"],
                        "away_book": best_away["bookmaker"],
                        "home_odds": int(best_home["odds"]),
                        "away_odds": int(best_away["odds"]),
                        "home_line": best_home["line"],
                        "away_line": best_away["line"],
                        "profit_margin": profit_margin,
                        "stake_home": stake_home,
                        "stake_away": stake_away,
                        "profit": profit
                    })

            elif m == "totals":
                over_rows = group[group["team"].str.lower().str.contains("over", na=False)]
                under_rows = group[group["team"].str.lower().str.contains("under", na=False)]
                if over_rows.empty or under_rows.empty:
                    continue

                best_over = over_rows.sort_values("odds", ascending=False).iloc[0]
                best_under = under_rows.sort_values("odds", ascending=False).iloc[0]

                over_line = best_over["line"]
                under_line = best_under["line"]
                if over_line is None or under_line is None:
                    continue
                if over_line != under_line:
                    continue

                dec_over = american_to_decimal(best_over["odds"])
                dec_under = american_to_decimal(best_under["odds"])
                arb_percent = (1/dec_over) + (1/dec_under)

                if arb_percent < 1:
                    profit_margin = (1 - arb_percent) * 100
                    stake_over, stake_under, profit = calculate_stakes(UNIT_SIZE, dec_over, dec_under)
                    arb_list.append({
                        "sport": sport,
                        "market": "Total",
                        "line_value": line_abs,
                        "home_team": home,
                        "away_team": away,
                        "start_time": start,
                        "over_book": best_over["bookmaker"],
                        "under_book": best_under["bookmaker"],
                        "over_odds": int(best_over["odds"]),
                        "under_odds": int(best_under["odds"]),
                        "over_line": best_over["line"],
                        "under_line": best_under["line"],
                        "profit_margin": profit_margin,
                        "stake_over": stake_over,
                        "stake_under": stake_under,
                        "profit": profit
                    })

# ---------------------------
# Step 3: Print top arbs
# ---------------------------
if not arb_list:
    print("⚠️ No arbitrage opportunities found for spreads/totals at this time.")
else:
    arb_df = pd.DataFrame(arb_list)
    for sport in SPORTS:
        sport_arbs = arb_df[arb_df["sport"] == sport].sort_values("profit_margin", ascending=False).head(TOP_N)
        if sport_arbs.empty:
            print(f"\n⚠️ No arbitrage opportunities found for {sport}.")
            continue

        print(f"\n🎯 Top {TOP_N} Arbitrage Opportunities for {sport.upper()}:")
        for _, arb in sport_arbs.iterrows():
            game_date = format_game_time(arb["start_time"])
            if arb["market"] == "Spread":
                print(f"\n💰 {arb['away_team']} vs {arb['home_team']}")
                print(f"   📅 Game Date: {game_date}")
                print(f"   📊 Market: Spread ({arb['line_value']})")
                print(f"   {arb['home_book']} → {arb['home_team']} ({arb['home_line']:+}) @ {format_american(arb['home_odds'])} (dec {american_to_decimal(arb['home_odds']):.2f})")
                print(f"   {arb['away_book']} → {arb['away_team']} ({arb['away_line']:+}) @ {format_american(arb['away_odds'])} (dec {american_to_decimal(arb['away_odds']):.2f})")
                print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
                print(f"   💵 Suggested Stakes: {arb['home_team']}: ${arb['stake_home']:.2f}, {arb['away_team']}: ${arb['stake_away']:.2f}")
                print(f"   💰 Guaranteed Profit: ${arb['profit']:.2f}")
            else:
                print(f"\n💰 {arb['away_team']} vs {arb['home_team']}")
                print(f"   📅 Game Date: {game_date}")
                print(f"   📊 Market: Total ({arb['line_value']})")
                print(f"   {arb['over_book']} → Over ({arb['over_line']}) @ {format_american(arb['over_odds'])} (dec {american_to_decimal(arb['over_odds']):.2f})")
                print(f"   {arb['under_book']} → Under ({arb['under_line']}) @ {format_american(arb['under_odds'])} (dec {american_to_decimal(arb['under_odds']):.2f})")
                print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
                print(f"   💵 Suggested Stakes: Over: ${arb['stake_over']:.2f}, Under: ${arb['stake_under']:.2f}")
                print(f"   💰 Guaranteed Profit: ${arb['profit']:.2f}")
