"""The NBA's official injury report: who is out, doubtful or questionable for each upcoming game.

The league posts it as a PDF several times a day (every 15 minutes on game days) and lists the links on
official.nba.com. ``pull_latest`` finds the newest one and caches it under ``data/raw/injuries/`` (one request for
the page, one for a PDF we haven't seen). ``parse`` reads the table by word position, because the PDF has no text
spacing to split on.

Not stats.nba.com, so it doesn't go through ``NBAClient``; any failure here is reported and skipped, never fatal:
the odds then simply carry no injury adjustment.

For games already played, ``pull_pregame`` keeps the last report posted before each tip-off (the league leaves old
reports up), so a game report can say who was out that night.
"""

from __future__ import annotations

import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

PAGE = "https://official.nba.com/nba-injury-report/"
LINK = re.compile(r"https://ak-static\.cms\.nba\.com/referee/injury/(Injury-Report_[A-Za-z0-9_\-]+\.pdf)")
STAMP = re.compile(r"_(\d{4}-\d{2}-\d{2})_(\d{2})(?:_(\d{2}))?(AM|PM)\.pdf$")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36"}
COLUMNS = ["report_time", "game_date", "matchup", "team_name", "player_name", "status", "reason"]

# Column starts (PDF points) of the report's table; a word belongs to the last column that starts at or before it.
_COLS = (("game_date", 0), ("game_time", 110), ("matchup", 195), ("team", 260), ("player", 420),
         ("status", 580), ("reason", 660))


def report_time(name: str) -> datetime | None:
    """The report's timestamp (US Eastern) from its file name, e.g. ``Injury-Report_2026-11-13_06_15PM.pdf``."""
    m = STAMP.search(name)
    if not m:
        return None
    return datetime.strptime(f"{m[1]} {m[2]}:{m[3] or '00'} {m[4]}", "%Y-%m-%d %I:%M %p")


def pull_latest(raw_dir: Path, timeout: float = 30) -> Path | None:
    """Download the newest injury report (if it isn't cached yet); returns its path, or None if it can't be had."""
    folder = raw_dir / "injuries"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        page = requests.get(PAGE, headers=HEADERS, timeout=timeout)
        page.raise_for_status()
        names = [n for n in set(LINK.findall(page.text)) if report_time(n)]
        if not names:
            return None
        name = max(names, key=report_time)
        path = folder / name
        if not path.exists():
            pdf = requests.get(f"https://ak-static.cms.nba.com/referee/injury/{name}", headers=HEADERS,
                               timeout=timeout)
            pdf.raise_for_status()
            if not pdf.content.startswith(b"%PDF"):
                return None
            path.write_bytes(pdf.content)
        return path
    except requests.RequestException:
        return None


def _name_at(t: pd.Timestamp) -> str:
    """The report file name for a 15-minute slot (US Eastern), in the league's current naming."""
    return f"Injury-Report_{t:%Y-%m-%d}_{t:%I}_{t:%M}{t:%p}.pdf"


def pull_pregame(raw_dir: Path, games: pd.DataFrame, tries: int = 8, timeout: float = 20) -> int:
    """For each played game (``game_id``, ``tipoff_utc``, ``away``, ``home``), cache the last report posted before
    tip-off as ``injuries/pregame/<game_id>.pdf``. Tries the 15-minute slots back from 15 minutes before tip-off
    (two hours at most); a game with none gets a ``.missing`` marker so it isn't asked for again. Returns how
    many reports were downloaded."""
    folder = raw_dir / "injuries" / "pregame"
    folder.mkdir(parents=True, exist_ok=True)
    got = 0
    for g in games.itertuples():
        pdf, missing = folder / f"{g.game_id}.pdf", folder / f"{g.game_id}.missing"
        if pdf.exists() or missing.exists():
            continue
        start = g.tipoff_utc.tz_convert("America/New_York").tz_localize(None).floor("15min") - pd.Timedelta(minutes=15)
        try:
            for i in range(tries):
                name = _name_at(start - pd.Timedelta(minutes=15 * i))
                r = requests.get(f"https://ak-static.cms.nba.com/referee/injury/{name}", headers=HEADERS,
                                 timeout=timeout)
                if r.status_code == 200 and r.content.startswith(b"%PDF"):
                    (folder / f"{g.game_id}.name").write_text(name, encoding="utf-8")
                    pdf.write_bytes(r.content)
                    got += 1
                    break
            else:
                missing.write_text("no report in the two hours before tip-off", encoding="utf-8")
        except requests.RequestException:
            continue  # the network, not the report: try again next pull
    return got


def pregame_table(raw_dir: Path) -> pd.DataFrame:
    """Every cached pre-game report's rows for its own game, with the ``game_id``."""
    frames = []
    for pdf in sorted((raw_dir / "injuries" / "pregame").glob("*.pdf")):
        gid = pdf.stem
        name_file = pdf.with_suffix(".name")
        name = name_file.read_text(encoding="utf-8").strip() if name_file.exists() else ""
        df = parse(pdf.read_bytes(), name)
        frames.append(df.assign(game_id=gid))
    if not frames:
        return pd.DataFrame(columns=["game_id"] + COLUMNS)
    return pd.concat(frames, ignore_index=True)


def latest_cached(raw_dir: Path) -> Path | None:
    files = [p for p in (raw_dir / "injuries").glob("Injury-Report_*.pdf") if report_time(p.name)]
    return max(files, key=lambda p: report_time(p.name)) if files else None


def _player(last_first: str) -> str:
    """"Williams, Jalen" -> "Jalen Williams"; "Johnson Jr., Morez" -> "Morez Johnson Jr."."""
    last, _, first = last_first.partition(",")
    return f"{first.strip()} {last.strip()}".strip()


def parse(pdf: bytes, name: str = "") -> pd.DataFrame:
    """Every player row in the report: game date, matchup (AWAY@HOME), team, player, status and reason.

    Rows only name the date, matchup and team on their first line, so those carry down (across pages too). A long
    reason wraps onto lines just above and below its player's line; each such line joins the nearest player row.
    """
    import pdfplumber  # only the pipeline needs it, not the website

    stamp = report_time(name)
    rows: list[dict] = []
    carry = {"game_date": None, "matchup": None, "team": None}
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for page in doc.pages:
            lines: dict[int, list[dict]] = {}
            for w in page.extract_words(x_tolerance=1.5):
                lines.setdefault(round(w["top"]), []).append(w)
            parsed = []
            for top in sorted(lines):
                cells: dict[str, list[str]] = {}
                for w in sorted(lines[top], key=lambda w: w["x0"]):
                    col = [c for c, x in _COLS if w["x0"] >= x - 2][-1]
                    cells.setdefault(col, []).append(w["text"])
                parsed.append((top, {c: " ".join(v) for c, v in cells.items()}))
            page_rows = []
            for top, c in parsed:
                whole = " ".join(c.values())
                if (c.get("game_date", "").startswith(("Injury", "Game")) or "Report:" in whole
                        or re.fullmatch(r"Page \d+ of \d+", whole)):
                    continue  # title, header and footer lines (the footer sits in the team column)
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", c.get("game_date", "")):
                    carry["game_date"] = c["game_date"]
                if re.fullmatch(r"[A-Z]{2,3}@[A-Z]{2,3}", c.get("matchup", "")):
                    carry["matchup"] = c["matchup"]
                if c.get("team"):
                    carry["team"] = c["team"]
                if c.get("player") and c.get("status"):
                    page_rows.append({"top": top, "game_date": carry["game_date"], "matchup": carry["matchup"],
                                      "team_name": carry["team"], "player_name": _player(c["player"]),
                                      "status": c["status"], "reason": [(top, c.get("reason", ""))]})
                elif c.get("reason") and not c.get("player") and "NOT YET SUBMITTED" not in c["reason"]:
                    page_rows.append({"top": top, "wrap": c["reason"]})
            players = [r for r in page_rows if "wrap" not in r]
            first_top = players[0]["top"] if players else float("inf")
            for r in page_rows:
                if "wrap" not in r:
                    continue
                near = min(players, key=lambda p: abs(p["top"] - r["top"])) if players else None
                if near is not None and abs(near["top"] - r["top"]) <= 16:
                    near["reason"].append((r["top"], r["wrap"]))  # wrapped just above or below its player's line
                elif r["top"] < first_top - 16 and rows:
                    rows[-1]["reason"] = f"{rows[-1]['reason']} {r['wrap']}".strip()  # ran over from the last page
            for p in players:
                text = " ".join(t for _, t in sorted(p.pop("reason")) if t)
                p["reason"] = re.sub(r"\s+/\s*|\s*/\s+", "/", re.sub(r"\s+", " ", text)).strip(" -")
                p.pop("top")
                rows.append(p)
    df = pd.DataFrame(rows, columns=[c for c in COLUMNS if c != "report_time"])
    df["game_date"] = pd.to_datetime(df["game_date"], format="%m/%d/%Y", errors="coerce")
    df.insert(0, "report_time", pd.Timestamp(stamp) if stamp else pd.NaT)
    return df.dropna(subset=["game_date", "matchup", "team_name"]).reset_index(drop=True)


def team_table(raw_dir: Path, team_abbreviation: str) -> pd.DataFrame | None:
    """The newest cached report's rows for games involving the team (both sides), or None if there is none."""
    path = latest_cached(raw_dir)
    if path is None:
        return None
    df = parse(path.read_bytes(), path.name)
    return df[df["matchup"].str.split("@").map(lambda t: team_abbreviation in t)].reset_index(drop=True)


def same_rows(a: pd.DataFrame, b: pd.DataFrame, extra: list[str] | None = None) -> bool:
    """Whether two tables list the same players and statuses (ignoring when the report was posted)."""
    cols = [c for c in COLUMNS if c != "report_time"] + (extra or [])
    if set(cols) - set(a.columns) or set(cols) - set(b.columns):
        return False
    key = lambda d: d[cols].astype(str).sort_values(cols).reset_index(drop=True)  # noqa: E731
    return key(a).equals(key(b))
