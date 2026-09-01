"""Build the Zoo Ryd3r Cup site from the Madden spreadsheets + cached ESPN data.

    python scripts/build_site.py --current 27 --previous 26 --season 2026

Reads:   M<cur>/M<prev> spreadsheets, data/espn/*.json, site/template.html
Writes:  site/build/index.html   (git-ignored: contains the password and rosters)

Then publish site/build/index.html as a Claude Artifact, replacing the existing
one so the league's link keeps working. See CLAUDE.md.

THE RULES THIS ENCODES (confirmed with the commissioner, Aug 2026):
  * One keeper per team.
  * Eligibility is stamped when you ACQUIRE a player and never re-judged, so the
    PREVIOUS Madden list governs players already on rosters and the CURRENT list
    governs anyone drafted this year (i.e. whether they can be kept next year).
  * Qualifies if <= 89 OVR on the governing list, OR was a rookie that year,
    OR was your keeper last season. The last-season exemption does NOT chain -
    skip a year and it is gone.
  * Lottery: winners bracket (final standings 1-4) seeded by placement; everyone
    else seeded by overall record INCLUDING playoffs, best to worst, with each
    playoff matchup counting as one game.
"""
import argparse, json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from zoolib import CEILING, ESPN_POS, ESPN_TO_MADDEN, name_key, creds

PLACE_W = {1: 3, 2: 5, 3: 6, 4: 8}      # odds for the winners bracket, by placement
SLOT_W = [10, 15, 20, 33]               # odds for 5th-8th, best record -> worst
ORD = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def load_madden(n):
    s = pd.read_excel(f"M{n} Player Ratings Spreadsheet.xlsx")
    d = pd.read_excel(f"madden_data_archives/M{n} (detailed).xlsx")
    team = d.set_index(["firstName", "lastName", "Position"])["Team"].to_dict()
    return [dict(name=f"{r['firstName']} {r['lastName']}", key=name_key(f"{r['firstName']} {r['lastName']}"),
                 pos=r["Position"], ovr=int(r["overallRating"]), yrs=int(r["yearsPro"]),
                 team=team.get((r["firstName"], r["lastName"], r["Position"]), ""))
            for _, r in s.iterrows()]


def join_years(cur, prev):
    """Match players across two Madden years. Falls back through position change
    and nickname (Kenneth -> Kenny) because EA is inconsistent between releases."""
    by_key, by_last = {}, {}
    for p in prev:
        by_key.setdefault((p["key"], p["pos"]), []).append(p)
        by_last.setdefault((p["key"][-8:], p["pos"]), []).append(p)
    by_name = {}
    for p in prev:
        by_name.setdefault(p["key"], []).append(p)

    rows, used, stats = [], set(), {"exact": 0, "pos": 0, "nick": 0}
    for a in cur:
        m = None
        c = by_key.get((a["key"], a["pos"]), [])
        if len(c) == 1:
            m, how = c[0], "exact"
        if m is None:
            c = by_name.get(a["key"], [])
            if len(c) == 1:
                m, how = c[0], "pos"
        if m is None:
            c = [x for x in by_last.get((a["key"][-8:], a["pos"]), []) if x["key"][:3] == a["key"][:3]]
            if len(c) == 1:
                m, how = c[0], "nick"
        if m is not None:
            used.add(id(m)); stats[how] += 1
        rows.append([a["name"], a["pos"], a["ovr"], a["yrs"], a["team"],
                     m["ovr"] if m else None, m["yrs"] if m else None, m["pos"] if m else None])
    for p in prev:
        if id(p) not in used:
            rows.append([p["name"], p["pos"], None, None, p["team"], p["ovr"], p["yrs"], p["pos"]])
    print(f"  joined: {stats} | {len(rows)} combined rows")
    return rows


def eligible(ovr, yrs):
    return ovr is not None and (ovr <= CEILING or yrs == 0)


def lottery(league_prev):
    """Seed the draft lottery from last season's real results."""
    teams = league_prev["teams"]
    mem = {m["id"]: (m.get("firstName") or "").strip() for m in league_prev.get("members", [])}
    rec, pf = {}, {}
    for t in teams:
        rec[t["id"]] = [0, 0]; pf[t["id"]] = 0.0
    for m in league_prev.get("schedule", []):
        h, a = m.get("home") or {}, m.get("away") or {}
        if not h or not a:
            continue
        pf[h["teamId"]] += h.get("totalPoints", 0); pf[a["teamId"]] += a.get("totalPoints", 0)
        w = m.get("winner")
        if w == "HOME":   rec[h["teamId"]][0] += 1; rec[a["teamId"]][1] += 1
        elif w == "AWAY": rec[a["teamId"]][0] += 1; rec[h["teamId"]][1] += 1
    out = []
    for t in teams:
        w, l = rec[t["id"]]
        out.append({"tid": t["id"], "name": t.get("name"),
                    "owner": ", ".join(mem.get(o, "?") for o in (t.get("owners") or [])),
                    "rank": t.get("rankCalculatedFinal"), "w": w, "l": l,
                    "pf": round(pf[t["id"]], 1)})
    ranks = sorted(x["rank"] for x in out)
    assert ranks == list(range(1, len(out) + 1)), f"bad final ranks {ranks} (need view=mStandings)"
    seed = []
    for v in sorted([x for x in out if x["rank"] <= 4], key=lambda x: x["rank"]):
        seed.append({**v, "weight": PLACE_W[v["rank"]], "basis": "finished " + ORD[v["rank"]]})
    rest = sorted([x for x in out if x["rank"] >= 5],
                  key=lambda x: (-(x["w"] / max(1, x["w"] + x["l"])), -x["pf"]))
    for i, v in enumerate(rest):
        seed.append({**v, "weight": SLOT_W[i], "basis": f"{v['w']}-{v['l']} overall"})
    seed.sort(key=lambda v: -v["weight"])
    assert sum(v["weight"] for v in seed) == 100, "lottery weights must sum to 100"
    return seed


def main(a):
    cur, prev = load_madden(a.current), load_madden(a.previous)
    players = join_years(cur, prev)
    mad = {name_key(p[0]): p for p in players}

    cur_lg = json.load(open(f"data/espn/league{a.season}.json"))
    prev_lg = json.load(open(f"data/espn/league{a.season - 1}.json"))
    names = json.load(open("data/espn/names.json"))

    seed = lottery(prev_lg)
    seed_by = {v["tid"]: v for v in seed}

    # last season's keepers, by team
    k_prev = {}
    for p in (prev_lg.get("draftDetail") or {}).get("picks") or []:
        if p.get("keeper"):
            rec = names.get(str(p["playerId"]))
            k_prev.setdefault(p["teamId"], []).append(rec["n"] if rec else f"#{p['playerId']}")

    # A keeper-eligible player carries his rights with him when traded, so index every
    # keeper by name -> the owner who declared him. Whoever holds him now inherits it.
    prev_mem = {m["id"]: (m.get("firstName") or "").strip() for m in prev_lg.get("members", [])}
    prev_owner = {t["id"]: ", ".join(prev_mem.get(o, "?") for o in (t.get("owners") or []))
                  for t in prev_lg.get("teams", [])}
    kmap = {}
    for tid, plist in k_prev.items():
        for nm in plist:
            kmap[name_key(nm)] = {"owner": prev_owner.get(tid, "?"), "name": nm}

    mem = {m["id"]: (m.get("firstName") or "").strip() for m in cur_lg.get("members", [])}
    teams, k25 = [], []
    for t in cur_lg["teams"]:
        kept = k_prev.get(t["id"], [])
        keeper = kept[0] if kept else ""
        owner = ", ".join(mem.get(o, "?") for o in (t.get("owners") or []))
        L = seed_by[t["id"]]
        roster, held = [], False
        for e in (t.get("roster") or {}).get("entries") or []:
            pl = e.get("playerPoolEntry", {}).get("player", {})
            nm, pos = pl.get("fullName"), ESPN_POS.get(pl.get("defaultPositionId"), "?")
            k = kmap.get(name_key(nm))            # was he anyone's keeper last season?
            isk = k is not None
            frm = "" if (not isk or k["owner"] == owner) else k["owner"]
            held = held or (nm == keeper)
            m = mad.get(name_key(nm)) if pos in ESPN_TO_MADDEN else None
            o_prev = m[5] if m else None; y_prev = m[6] if m else None
            o_cur = m[2] if m else None
            by_rule = eligible(o_prev, y_prev)
            roster.append([nm, pos, o_prev, o_cur, int(by_rule or isk), int(isk),
                           int(isk and not by_rule), frm])
        roster.sort(key=lambda r: (-r[4], -(r[2] if r[2] is not None else -1)))
        teams.append({"id": t["id"], "name": t.get("name"), "owner": owner, "rank": L["rank"],
                      "rec": f"{L['w']}-{L['l']}", "pf": L["pf"], "weight": L["weight"],
                      "basis": L["basis"], "k25": keeper, "k25held": held, "roster": roster})
        m = mad.get(name_key(keeper))
        row = next((r for r in roster if r[0] == keeper), None)
        k25.append({"owner": owner, "team": t.get("name"), "player": keeper,
                    "pos": row[1] if row else (m[1] if m else "?"),
                    "ovr26": m[5] if m else None, "ovr27": m[2] if m else None,
                    "held": held, "ex": bool(row[6]) if row else False, "now": ""})
    # if a keeper was traded away, say who holds him now - the rights went with him
    where = {}
    for t in teams:
        for r in t["roster"]:
            where[name_key(r[0])] = t
    for k in k25:
        if not k["held"] and k["player"]:
            holder = where.get(name_key(k["player"]))
            k["now"] = f"{holder['name']} ({holder['owner']})" if holder else ""

    teams.sort(key=lambda t: -t["weight"])
    order = [t["id"] for t in teams]
    k25.sort(key=lambda k: order.index(next(t["id"] for t in teams if t["name"] == k["team"])))

    history = []
    for y in sorted([int(f[6:10]) for f in os.listdir("data/espn")
                     if f.startswith("league")], reverse=True):
        lg = json.load(open(f"data/espn/league{y}.json"))
        picks = [p for p in ((lg.get("draftDetail") or {}).get("picks") or []) if p.get("keeper")]
        if not picks:
            continue
        m2 = {m["id"]: (m.get("firstName") or "").strip() for m in lg.get("members", [])}
        ti = {t["id"]: t for t in lg.get("teams", [])}
        rows = {}
        for p in sorted(picks, key=lambda x: x["overallPickNumber"]):
            t = ti.get(p["teamId"], {})
            r = names.get(str(p["playerId"]))
            label = f"{r['n']} ({ESPN_POS.get(r['p'], '?')})" if r else f"#{p['playerId']}"
            rows.setdefault(p["teamId"], {"owner": ", ".join(m2.get(o, "?") for o in (t.get("owners") or [])),
                                          "team": t.get("name"), "players": []})["players"].append(label)
        history.append({"year": y, "rows": [rows[k] for k in sorted(rows)]})

    payload = {"draft": a.draft, "keeperCount": 1, "players": players,
               "teams": teams, "k25": k25, "history": history}

    tpl = open("site/template.html").read()
    pw = creds().get("SITE_PASSWORD")
    if not pw:
        raise SystemExit("SITE_PASSWORD missing from ~/.config/zoo-espn/creds.env")
    # comma-separated list; the gate strips case/space/punctuation before comparing
    pws = [x.strip() for x in pw.split(",") if x.strip()]
    html = tpl.replace("__DATA__", json.dumps(payload, separators=(",", ":"))) \
              .replace("__PASSWORDS__", json.dumps(pws))
    assert "__DATA__" not in html and "__PASSWORDS__" not in html
    print(f"  accepted passwords: {pws}")
    os.makedirs("docs", exist_ok=True)
    open("docs/index.html", "w").write(html)                 # served by GitHub Pages
    open("docs/.nojekyll", "w").write("")
    os.makedirs("site/build", exist_ok=True)
    open("site/build/index.html", "w").write(html)           # local copy for publishing
    print(f"  built docs/index.html + site/build/index.html ({len(html):,} bytes)")
    print(f"  {len(teams)} teams | {len(players)} players | history {[h['year'] for h in history]}")
    for t in teams:
        print(f"    {t['weight']:>3}%  {t['name'][:28]:<29} {t['owner']:<9} {t['basis']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="27"); ap.add_argument("--previous", default="26")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--draft", default="Wednesday, September 2, 2026 at 8:00 PM")
    main(ap.parse_args())
