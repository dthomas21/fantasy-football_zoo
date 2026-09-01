"""Pull a Madden launch-ratings set from EA and write the league's two spreadsheets.

    python scripts/fetch_madden.py 27

Writes:
    M<N> Player Ratings Spreadsheet.xlsx   (repo root, QB/HB/WR/TE, 5 cols)
    madden_data_archives/M<N> (detailed).xlsx  (all positions, 124 cols)

Source is EA's own ratings site data route, which is where the historical
"(detailed)" files came from - hence the identical column layout.
The older drop-api.ea.com endpoint serves stale data; do not use it.
"""
import json, math, re, sys, time
import pandas as pd, requests

BASE = "https://www.ea.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

STAT_KEYS = ['acceleration','agility','jumping','stamina','strength','awareness','bCVision',
 'blockShedding','breakSack','breakTackle','carrying','catchInTraffic','catching',
 'changeOfDirection','deepRouteRunning','finesseMoves','hitPower','impactBlocking','injury',
 'jukeMove','kickAccuracy','kickPower','kickReturn','leadBlock','manCoverage','mediumRouteRunning',
 'overall','passBlock','passBlockFinesse','passBlockPower','playAction','playRecognition',
 'powerMoves','press','pursuit','release','runBlock','runBlockFinesse','runBlockPower',
 'runningStyle','shortRouteRunning','spectacularCatch','speed','spinMove','stiffArm','tackle',
 'throwAccuracyDeep','throwAccuracyMid','throwAccuracyShort','throwOnTheRun','throwPower',
 'throwUnderPressure','toughness','trucking','zoneCoverage']

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from zoolib import FANTASY_POS


def fetch_all():
    s = requests.Session(); s.headers.update({"User-Agent": UA})
    html = s.get(f"{BASE}/games/madden-nfl/ratings", timeout=20).text
    m = re.search(r"/_next/static/([^/]+)/_buildManifest\.js", html)
    if not m:
        raise SystemExit("Could not find the Next.js build id - EA changed their site.")
    tmpl = f"{BASE}/_next/data/{m.group(1)}/games/madden-nfl/ratings.json?page={{}}"
    r = s.get(tmpl.format(1), timeout=25); r.raise_for_status()
    rd = r.json()["pageProps"]["ratingDetails"]
    pages = math.ceil(rd["totalItems"] / 100)
    print(f"  {rd['totalItems']} players across {pages} pages")
    out = list(rd["items"])
    for pg in range(2, pages + 1):
        time.sleep(0.8)
        out.extend(s.get(tmpl.format(pg), timeout=25).json()["pageProps"]["ratingDetails"]["items"])
        print(f"    page {pg}/{pages}", end="\r")
    seen, uniq = set(), []
    for p in out:
        if p["id"] not in seen:
            seen.add(p["id"]); uniq.append(p)
    return uniq


def birthdate(s):
    if not s: return None
    try:
        from datetime import datetime
        d = datetime.strptime(s[:10], "%Y-%m-%d")
        return f"{d.month}/{d.day}/{d.strftime('%y')}"
    except Exception:
        return s


def main(n):
    raw = fetch_all()
    iters = {p["iteration"]["label"] for p in raw}
    print(f"\n  iterations present: {iters}")
    if iters != {"Launch Ratings"}:
        print("  WARNING: not purely launch ratings - the keeper rule uses the FIRST public list.")
    rows = []
    for p in raw:
        st = p.get("stats") or {}
        r = {"firstName": p.get("firstName"), "lastName": p.get("lastName"),
             "Team": (p.get("team") or {}).get("label"),
             "Position": (p.get("position") or {}).get("id"),
             "college": p.get("college"), "age": p.get("age"),
             "overallRating": p.get("overallRating"), "birthdate": birthdate(p.get("birthdate")),
             "height": p.get("height"), "weight": p.get("weight"),
             "handedness": p.get("handedness"), "jerseyNum": p.get("jerseyNum"),
             "yearsPro": p.get("yearsPro"), "Archetype": (p.get("archetype") or {}).get("label")}
        for k in STAT_KEYS:
            v = st.get(k) or {}
            r[f"stats/{k}/value"] = v.get("value"); r[f"stats/{k}/diff"] = v.get("diff")
        rows.append(r)
    det = pd.DataFrame(rows).sort_values("overallRating", ascending=False,
                                         kind="mergesort").reset_index(drop=True)
    det.to_excel(f"madden_data_archives/M{n} (detailed).xlsx",
                 sheet_name="Launch Ratings", index=False)
    simp = det[det["Position"].isin(FANTASY_POS)][
        ["firstName", "lastName", "Position", "overallRating", "yearsPro"]].reset_index(drop=True)
    simp.to_excel(f"M{n} Player Ratings Spreadsheet.xlsx", sheet_name="Sheet1", index=False)
    print(f"  detailed  {det.shape} -> madden_data_archives/M{n} (detailed).xlsx")
    print(f"  simplified {simp.shape} -> M{n} Player Ratings Spreadsheet.xlsx")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/fetch_madden.py <madden number, e.g. 28>")
    main(sys.argv[1])
