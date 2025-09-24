import requests
import pandas as pd
from datetime import datetime
import pytz

# ---------- CONFIG ----------
API_KEY = "f7aa230a8379043a6fee01e111290300"
REGION = "us"
UNIT_SIZE = 1000
TOP_N = 5
ROUND_TO = 5

# Sports to scan for player props
SPORTS = ["americanfootball_nfl", "americanfootball_ncaaf"]

# Player prop markets to scan
PLAYER_MARKETS = [
    "player_pass_yds", "player_rush_yds", "player_pass_tds", "player_rush_tds",
    "player_receptions", "player_receiving_yds", "player_pass_attempts"
]

# Optional whitelist of bookmakers (None = allow all)
ALLOWED_BOOK_KEYS = ["draftkings", "fanduel"]

REQUEST_TIMEOUT = 10  # seconds for API calls
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
# Step 0: Fetch events per sport
# ---------------------------
events_data = []
for sport in SPORTS:
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/"
    params = {"apiKey": API_KEY, "regions": REGION}
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Error fetching {sport} events:", e)
        continue

    events = resp.json()
    if not events:
        print(f"⚠️ No events returned for {sport}")
        continue

    for ev in events:
        events_data.append({
            "sport": sport,
            "event_id": ev.get("id"),
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
            "commence_time": ev.get("commence_time")
        })

if not events_data:
    print("⚠️ No events available. Exiting.")
    raise SystemExit(0)

events_df = pd.DataFrame(events_data)
print(f"✅ Retrieved {len(events_df)} events across sports.")

# ---------------------------
# Step 1: Fetch player props for each event
# ---------------------------
rows = []
for _, ev in events_df.iterrows():
    sport = ev["sport"]
    event_id = ev["event_id"]
    url = f"https://api.the-odds-api.com/v4/events/{event_id}/odds/"
    params = {
        "apiKey": API_KEY,
        "regions": REGION,
        "markets": ",".join(PLAYER_MARKETS),
        "oddsFormat": "american",
        "dateFormat": "iso"
    }
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Error fetching odds for event {event_id}:", e)
        continue

    data = resp.json()
    bookmakers = data.get("bookmakers", [])
    for book in bookmakers:
        if ALLOWED_BOOK_KEYS and book.get("key") not in ALLOWED_BOOK_KEYS:
            continue
        book_title = book.get("title")
        for market in book.get("markets", []):
            if market.get("key") not in PLAYER_MARKETS:
                continue
            for outcome in market.get("outcomes", []):
                rows.append({
                    "sport": sport,
                    "event_id": event_id,
                    "market": market.get("key"),
                    "home_team": ev["home_team"],
                    "away_team": ev["away_team"],
                    "commence_time": ev["commence_time"],
                    "bookmaker": book_title,
                    "team": outcome.get("name"),
                    "line": outcome.get("point"),
                    "odds": outcome.get("price")
                })

if not rows:
    print("⚠️ No player prop odds found. Exiting.")
    raise SystemExit(0)

df = pd.DataFrame(rows)
df["odds"] = pd.to_numeric(df["odds"], errors="coerce")
df["line"] = pd.to_numeric(df["line"], errors="coerce")
print(f"✅ Parsed {len(df)} player prop entries into the DataFrame.")

# ---------------------------
# Step 2: Find arbitrage opportunities
# ---------------------------
arb_list = []

for market in PLAYER_MARKETS:
    sub = df[df["market"] == market]
    if sub.empty:
        continue

    # Group by event and market to compare identical props
    group_cols = ["sport", "event_id", "market", "team", "commence_time"]
    groups = sub.groupby(group_cols, dropna=False)

    # Compare over/under pairs for same player prop
    for (s, eid, m, team, start), group in groups:
        over_row = group[group["team"].str.lower().str.contains("over", na=False)]
        under_row = group[group["team"].str.lower().str.contains("under", na=False)]
        if over_row.empty or under_row.empty:
            continue

        best_over = over_row.sort_values("odds", ascending=False).iloc[0]
        best_under = under_row.sort_values("odds", ascending=False).iloc[0]

        dec_over = american_to_decimal(best_over["odds"])
        dec_under = american_to_decimal(best_under["odds"])
        arb_percent = (1/dec_over) + (1/dec_under)

        if arb_percent < 1:
            profit_margin = (1 - arb_percent) * 100
            stake_over, stake_under, profit = calculate_stakes(UNIT_SIZE, dec_over, dec_under)
            arb_list.append({
                "sport": s,
                "market": m,
                "player": team,
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
    print("⚠️ No arbitrage opportunities found for player props.")
else:
    arb_df = pd.DataFrame(arb_list)
    for sport in SPORTS:
        sport_arbs = arb_df[arb_df["sport"] == sport].sort_values("profit_margin", ascending=False).head(TOP_N)
        if sport_arbs.empty:
            print(f"\n⚠️ No arbitrage opportunities found for {sport}.")
            continue

        print(f"\n🎯 Top {TOP_N} Player Prop Arbitrage Opportunities for {sport.upper()}:")
        for _, arb in sport_arbs.iterrows():
            game_date = format_game_time(arb["start_time"])
            print(f"\n💰 Player: {arb['player']}")
            print(f"   📅 Game Date: {game_date}")
            print(f"   📊 Market: {arb['market']}")
            print(f"   {arb['over_book']} → Over ({arb['over_line']}) @ {format_american(arb['over_odds'])} (dec {american_to_decimal(arb['over_odds']):.2f})")
            print(f"   {arb['under_book']} → Under ({arb['under_line']}) @ {format_american(arb['under_odds'])} (dec {american_to_decimal(arb['under_odds']):.2f})")
            print(f"   ✅ Profit Margin: {arb['profit_margin']:.2f}%")
            print(f"   💵 Suggested Stakes: Over: ${arb['stake_over']:.2f}, Under: ${arb['stake_under']:.2f}")
            print(f"   💰 Guaranteed Profit: ${arb['profit']:.2f}")
