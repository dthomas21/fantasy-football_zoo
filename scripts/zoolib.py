"""Shared helpers for the Zoo Ryd3r Cup toolchain."""
import os, re, unicodedata

CEILING = 89                      # Madden OVR at or below which a player is keeper-eligible
FANTASY_POS = ["QB", "HB", "WR", "TE"]      # Madden position ids we care about
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
ESPN_TO_MADDEN = {"RB": "HB", "QB": "QB", "WR": "WR", "TE": "TE"}

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def name_key(s):
    """Normalise a player name for cross-source matching.

    EA flips name suffixes between Madden years (James Cook -> James Cook III,
    Kenneth Walker III -> Kenneth Walker) and ESPN spells them differently again,
    so the suffix has to come off or joins silently drop players.
    """
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", _SUFFIX.sub(" ", s).lower())


def creds(path="~/.config/zoo-espn/creds.env"):
    """Read the local, git-ignored credentials file. Never commit these values."""
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise SystemExit(
            f"Missing {p}\n"
            "Create it with LEAGUE_ID, ESPN_S2, SWID and SITE_PASSWORD.\n"
            "See CLAUDE.md > Credentials."
        )
    out = {}
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out
