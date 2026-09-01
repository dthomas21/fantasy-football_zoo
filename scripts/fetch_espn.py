"""Cache the ESPN league data the site needs.

    python scripts/fetch_espn.py            # current + previous season
    python scripts/fetch_espn.py 2026 2025 2024

Writes JSON into data/espn/ (git-ignored - it contains rosters and owner names).

Notes learned the hard way:
  * host must be lm-api-reads.fantasy.espn.com; fantasy.espn.com 302s
  * fields only appear when you ask for the matching view
  * rankFinal is ALWAYS 0 - real placement is rankCalculatedFinal (needs mStandings)
  * /players returns 50 rows unless you send an x-fantasy-filter header
  * draft picks carry a `keeper` boolean - that is the keeper history
"""
import json, os, sys, time
import requests

sys.path.insert(0, os.path.dirname(__file__))
from zoolib import creds

HOST = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
VIEWS = ["mTeam", "mSettings", "mRoster", "mStandings", "mMatchup", "mDraftDetail"]
OUT = "data/espn"


def session(c):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Cookie": f"espn_s2={c['ESPN_S2']}; SWID={c['SWID']}"})
    return s


def league(s, league_id, year):
    q = "&".join("view=" + v for v in VIEWS)
    r = s.get(f"{HOST}/{year}/segments/0/leagues/{league_id}?{q}", timeout=30)
    if r.status_code == 401:
        raise SystemExit("401 from ESPN - your espn_s2 cookie has expired. Grab a fresh one "
                         "(DevTools > Application > Cookies) and update creds.env.")
    r.raise_for_status()
    return r.json()


def players(s, year, ids):
    """Resolve player ids to names. Needs the filter header or you get 50 rows."""
    hdr = {"x-fantasy-filter": json.dumps({"players": {"filterIds": {"value": list(ids)},
                                                       "limit": 2000}})}
    r = s.get(f"{HOST}/{year}/players?view=players_wl", headers=hdr, timeout=40)
    r.raise_for_status()
    want = set(ids)
    return {p["id"]: {"n": p.get("fullName"), "p": p.get("defaultPositionId")}
            for p in r.json() if p["id"] in want}


def main(years):
    c = creds(); s = session(c); lid = c["LEAGUE_ID"]
    os.makedirs(OUT, exist_ok=True)
    keeper_ids = set()
    for y in years:
        d = league(s, lid, y)
        json.dump(d, open(f"{OUT}/league{y}.json", "w"))
        picks = (d.get("draftDetail") or {}).get("picks") or []
        ks = [p for p in picks if p.get("keeper")]
        keeper_ids |= {p["playerId"] for p in ks}
        print(f"  {y}: {len(d.get('teams', []))} teams, {len(picks)} picks, {len(ks)} keepers")
        time.sleep(0.4)
    names = {}
    for y in sorted(years, reverse=True):          # newest first; retirees need older seasons
        missing = keeper_ids - set(names)
        if not missing:
            break
        names.update(players(s, y, missing)); time.sleep(0.4)
    json.dump({str(k): v for k, v in names.items()}, open(f"{OUT}/names.json", "w"))
    print(f"  resolved {len(names)}/{len(keeper_ids)} keeper names -> {OUT}/names.json")
    if len(names) < len(keeper_ids):
        print("  (unresolved ids are usually players retired out of every cached season)")


if __name__ == "__main__":
    yrs = [int(a) for a in sys.argv[1:]]
    if not yrs:
        import datetime
        n = datetime.date.today().year
        yrs = [n, n - 1]
    main(yrs)
