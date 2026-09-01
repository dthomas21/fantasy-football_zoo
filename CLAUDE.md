# Zoo Ryd3r Cup — project context

Fantasy football league tooling: Madden ratings drive keeper eligibility, a weighted
lottery sets the draft order, and a private web page ties it together for the owners.
League is **Zoo Hau5 OYB** on ESPN, 8 teams, running since 2014.

**This repo is public.** League data (rosters, owner names) and the site password are
git-ignored and live locally. Never commit anything from `data/` or `site/build/`.

---

## The keeper rule, as actually practised

Confirmed with the commissioner in Aug 2026. The README's original 2019 text is out of
date in one respect — it says two keepers; it has been **one per team since 2021**, and
ESPN is configured `keeperCount: 1`. (2020 was the only two-keeper year.)

A player is keeper-eligible if **any** of these hold:

1. Rated **89 OVR or below** on the Madden list in force when you acquired him.
2. He was a **rookie** that year — rookies are exempt from the ceiling entirely.
3. He was **your keeper last season**. No Madden check needed.

Two things people get wrong:

- **Eligibility is stamped at acquisition and never re-judged.** A player you got when he
  was 80 OVR stays keepable at 96. This is why the *previous* Madden list governs players
  already on rosters, and the *current* list governs anyone drafted this year (deciding
  whether they can be kept next year). Judging a current roster against the newest ratings
  gives wrong answers.
- **The last-season exemption does not chain.** Kept him in 2024, skipped 2025, and he has
  since gone 90+? He is gone.

## The draft lottery

Weights are 33/20/15/10 then 8/6/5/3, assigned by a **hybrid** rule:

- **Winners bracket (final standings 1–4):** seeded by placement. 1st place gets the worst
  odds (3%).
- **Everyone else (5th–8th):** seeded by **overall record including playoffs, best to
  worst** — each playoff matchup counts as ONE game though it spans two scoring weeks.
  Best record of the four gets 10%, worst gets 33%.

Names are drawn one at a time without replacement, remaining weights renormalised after
each pick — matching `numpy.random.choice(replace=False, p=...)` in the original notebooks
under `code/`. Owners then choose their draft slot in the order drawn.

## Prizes / punishment

1st $500, 2nd $200, 3rd $100. Loser's costume decided by group vote.

---

## Rebuilding the site

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/fetch_madden.py 28            # new Madden each August
.venv/bin/python scripts/fetch_espn.py 2027 2026       # + any older years for history
.venv/bin/python scripts/build_site.py --current 28 --previous 27 --season 2027
```

`build_site.py` writes `site/build/index.html`. Publish that as a **Claude Artifact**,
passing the existing artifact URL as `url` so the league's bookmark keeps working —
publishing without it mints a new link and orphans the old one.

The URL, the site password and the ESPN cookies all live in
**`~/.config/zoo-espn/creds.env`** (chmod 600, outside this repo).

`site/template.html` is the page itself — HTML/CSS/JS with `__DATA__` and `__PASSWORD__`
placeholders. Edit it directly for design or feature changes, then rebuild.

## Data sources

- **Madden** — EA's own ratings site data route
  (`ea.com/_next/data/{buildId}/games/madden-nfl/ratings.json`). The historical
  `(detailed)` archives came from here, hence the matching 124-column layout.
  The older `drop-api.ea.com` endpoint serves **stale** data — don't use it.
  Only the **launch** ratings count for the keeper rule (`iteration: 1-base`).
- **ESPN** — `lm-api-reads.fantasy.espn.com`. Private league, so cookies are required.

## Gotchas that have already cost time

- ESPN's `rankFinal` is **always 0**. Real placement is **`rankCalculatedFinal`**, and only
  with `view=mStandings`. Fields appear only when you request the matching view.
- ESPN `/players` returns just 50 rows unless you send an `x-fantasy-filter` header.
  Retired players are missing from recent seasons and must be pulled from an older one.
- **Name matching is the main source of silent bugs.** Suffixes flip between sources and
  between Madden years (`James Cook` ⇄ `James Cook III`, `Kenneth Walker III` ⇄
  `Kenneth Walker`), and first names vary (`Kenneth`/`Kenny` Gainwell). An early join lost
  12 players including two who were on the keep-now-or-never list. `zoolib.name_key()`
  strips suffixes; `build_site.py` also falls back through position change and nickname.
  **If a join looks clean, check the unmatched veterans — rookies are expected to be
  unmatched, veterans usually are not.**
- Madden calls running backs **HB**; ESPN calls them **RB**.
- Madden 27 renamed defensive positions (`LE`→`LEDG`, `MLB`→`MIKE`, `LOLB`→`SAM`,
  `ROLB`→`WILL`). Fantasy positions are unchanged.
- If ESPN starts returning **401**, the `espn_s2` cookie expired. Get a fresh one from
  DevTools → Application → Cookies → `fantasy.espn.com`.

## Layout

```
M<N> Player Ratings Spreadsheet.xlsx   current + previous Madden, QB/HB/WR/TE, 5 cols
madden_data_archives/                  older years + every "(detailed)" full export
code/                                  original per-year draft lottery notebooks
dt_personal/                           Darren's own draft-prep sheets
scripts/                               fetch + build pipeline
site/template.html                     the web page (no data, no password)
site/build/                            generated, git-ignored
data/espn/                             ESPN cache, git-ignored
```
