"""Data for the Streamlit dashboard: pure functions over the processed tables.

Kept separate from ``dashboard/app.py`` so it can be tested without Streamlit,
and so the dashboard never touches the network or the raw cache: it reads
``data/processed/`` only, the same tables the report uses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np
import pandas as pd

from courtside.names import short_names
from courtside.analysis.decompose import FACTOR_LABELS, FACTORS, decompose_frame
from courtside.transform.halves import summarize
from courtside.transform.league_context import METRICS
from courtside.transform.turnovers import summarize_players

LEAD_CLASS_LABELS = {
    "blown_lead": "Blown lead",
    "held_lead": "Held lead",
    "never_led_big": "No big early lead",
}
METRIC_LABELS = {
    "net_rtg": "Net rating",
    "ortg": "Scoring (offensive rating)",
    "drtg": "Defense (points allowed per 100)",
    "efg_pct": "Shooting accuracy (eFG%)",
    "opp_efg_pct": "Opponents' shooting (eFG%)",
    "tov_pct": "Turnover rate",
    "opp_ft_rate": "Opponent free throws per shot",
    "oreb_pct": "Offensive rebounding",
    "opp_oreb_pct": "Second chances given up",
    "pf_per100": "Fouls per 100 possessions",
    "pace": "Pace (possessions)",
}
# (label, column, format) rows for the per-game half comparison.
GAME_ROWS = [
    ("Points", "pts", "{:.0f}"),
    ("Opponent points", "opp_pts", "{:.0f}"),
    ("Margin", "margin", "{:+.0f}"),
    ("Shooting accuracy", "efg_pct", "{:.1%}"),
    ("Opponents' shooting accuracy", "opp_efg_pct", "{:.1%}"),
    ("Turnovers", "tov_all", "{:.0f}"),
    ("Opponent points off turnovers", "opp_pts_off_tov", "{:.0f}"),
    ("Second chances given up", "opp_oreb", "{:.0f}"),
    ("Opponent free throws attempted", "opp_fta", "{:.0f}"),
    ("Fouls", "pf", "{:.0f}"),
]


@dataclass
class DashboardData:
    game_halves: pd.DataFrame
    game_leads: pd.DataFrame
    margins: pd.DataFrame
    player_stats: pd.DataFrame
    turnovers: pd.DataFrame
    ranks: pd.DataFrame
    analysis: dict
    games: pd.DataFrame
    comparison: pd.DataFrame
    attribution: dict[str, pd.DataFrame]
    player_box: pd.DataFrame
    lineups: pd.DataFrame
    history: pd.DataFrame
    onoff: pd.DataFrame = field(default_factory=pd.DataFrame)
    matchups: pd.DataFrame = field(default_factory=pd.DataFrame)
    hustle: pd.DataFrame = field(default_factory=pd.DataFrame)
    bio: pd.DataFrame = field(default_factory=pd.DataFrame)
    segments: pd.DataFrame = field(default_factory=pd.DataFrame)
    plays: pd.DataFrame = field(default_factory=pd.DataFrame)
    schedule: pd.DataFrame = field(default_factory=pd.DataFrame)
    league_periods: pd.DataFrame = field(default_factory=pd.DataFrame)
    player_season: pd.DataFrame = field(default_factory=pd.DataFrame)
    team_misc: pd.DataFrame = field(default_factory=pd.DataFrame)
    roster: pd.DataFrame = field(default_factory=pd.DataFrame)
    shots: pd.DataFrame = field(default_factory=pd.DataFrame)
    injuries: pd.DataFrame = field(default_factory=pd.DataFrame)
    game_injuries: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def seasons(self) -> list[str]:
        return sorted(self.game_leads["season"].unique(), reverse=True)


# The pages build HTML from names and labels in the data (stats.nba.com). Those never legitimately contain these
# characters, so they're removed where the data loads: whatever a source sends, it can't become markup or script.
_UNSAFE = re.compile(r'[<>"`]')


def clean_text(value):
    """``value`` with the characters that could open a tag or break out of an attribute removed; non-text
    values (numbers, dates) pass through, and lists or tuples of names are cleaned item by item."""
    if isinstance(value, str):
        return _UNSAFE.sub("", value)
    if isinstance(value, (list, tuple)):
        return type(value)(clean_text(v) for v in value)
    if isinstance(value, np.ndarray) and value.dtype == object:
        return np.array([clean_text(v) for v in value], dtype=object)
    if isinstance(value, dict):
        return {k: clean_text(v) for k, v in value.items()}
    return value


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Every text column (and list-of-names column) of ``df`` run through ``clean_text``."""
    out = df.copy()
    for col in out.columns:
        s_ = out[col]
        if pd.api.types.is_string_dtype(s_) or s_.dtype == object:
            out[col] = s_.map(clean_text)
    return out


def load(processed_dir: Path, analysis_json: Path) -> DashboardData:
    """Read every table the dashboard uses, with all text cleaned (see ``clean_text``)."""
    raw = _load(processed_dir, analysis_json)
    for f in fields(raw):
        v = getattr(raw, f.name)
        if isinstance(v, pd.DataFrame):
            setattr(raw, f.name, clean_frame(v))
        elif f.name == "attribution":
            setattr(raw, f.name, {k: clean_frame(df) for k, df in v.items()})
        elif f.name == "analysis":
            setattr(raw, f.name, clean_text(v))
    return raw


def _load(processed_dir: Path, analysis_json: Path) -> DashboardData:
    p = Path(processed_dir)
    analysis = json.loads(Path(analysis_json).read_text(encoding="utf-8")) if Path(analysis_json).exists() else {}
    a = p / "analysis"
    meta = analysis.get("meta", {})
    attribution = {}
    for season, name in ((meta.get("season"), "attribution.csv"), (meta.get("comparison_season"), "attribution_prior.csv")):
        if season and (a / name).exists():
            attribution[season] = pd.read_csv(a / name)

    def optional(name: str) -> pd.DataFrame:
        return pd.read_parquet(p / f"{name}.parquet") if (p / f"{name}.parquet").exists() else pd.DataFrame()

    return DashboardData(
        game_halves=pd.read_parquet(p / "game_halves.parquet"),
        game_leads=pd.read_parquet(p / "game_leads.parquet"),
        margins=pd.read_parquet(p / "margin_series.parquet"),
        player_stats=pd.read_parquet(p / "player_half_stats.parquet"),
        turnovers=pd.read_parquet(p / "turnover_events.parquet"),
        ranks=pd.read_parquet(p / "league_half_ranks.parquet"),
        analysis=analysis,
        games=pd.read_parquet(p / "games.parquet"),
        comparison=pd.read_csv(a / "season_comparison.csv") if (a / "season_comparison.csv").exists() else pd.DataFrame(),
        attribution=attribution,
        player_box=pd.read_parquet(p / "player_box.parquet"),
        lineups=pd.read_parquet(p / "lineup_halves.parquet"),
        history=optional("player_history_halves"),
        onoff=optional("onoff_halves"),
        matchups=optional("matchups"),
        hustle=optional("hustle"),
        bio=optional("player_bio"),
        segments=optional("segments"),
        plays=optional("plays"),
        schedule=optional("schedule"),
        league_periods=optional("league_periods"),
        player_season=optional("player_season"),
        team_misc=optional("team_misc"),
        roster=optional("roster"),
        shots=optional("shots"),
        injuries=optional("injuries"),
        game_injuries=optional("game_injuries"),
    )


# ------------------------------------------------------------------ games

def game_options(leads: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per game, newest first, with a readable label for a selector."""
    g = leads[leads["season"] == season].sort_values("game_date", ascending=False).copy()
    date = pd.to_datetime(g["game_date"]).dt.strftime("%b %d").str.replace(" 0", " ")
    where = g["is_home"].map({True: "vs", False: "at"})
    ot = g["overtime_periods"].map(lambda n: f" ({n}OT)" if n else "")
    tag = g["lead_class"].map(LEAD_CLASS_LABELS).fillna("")
    g["label"] = (date + " " + where + " " + g["opponent_abbreviation"] + "  " + g["result"] + " "
                  + g["final_margin"].map("{:+d}".format) + ot + "  ·  " + tag)
    return g[["game_id", "label", "lead_class", "max_lead", "halftime_margin", "final_margin"]].reset_index(drop=True)


def game_margin(margins: pd.DataFrame, game_id: str) -> pd.DataFrame:
    m = margins[margins["game_id"] == game_id].sort_values("elapsed")
    return m.assign(minute=m["elapsed"] / 60)


def game_half_table(game_halves: pd.DataFrame, game_id: str) -> pd.DataFrame:
    """First half vs second half for one game, formatted for display."""
    g = game_halves[(game_halves["game_id"] == game_id) & game_halves["split"].astype(str).isin(["H1", "H2"])]
    s = summarize(g.assign(split=g["split"].astype(str)), ["split"]).set_index("split")
    s["margin"] = s["pts"] - s["opp_pts"]
    s["tov_all"] = s["tov"] + s.get("tov_team", 0)
    rows = []
    for label, col, fmt in GAME_ROWS:
        h1, h2 = s.loc["H1", col], s.loc["H2", col]
        change = f"{100 * (h2 - h1):+.1f} pts" if "%" in fmt else f"{h2 - h1:+.0f}"
        rows.append({"stat": label, "1st half": fmt.format(h1), "2nd half": fmt.format(h2), "change": change})
    return pd.DataFrame(rows)


def game_attribution(game_halves: pd.DataFrame, game_id: str) -> pd.DataFrame:
    """Exact decomposition of one game's 1H -> 2H margin change."""
    g = game_halves[(game_halves["game_id"] == game_id) & game_halves["split"].astype(str).isin(["H1", "H2"])]
    d = decompose_frame(g.assign(split=g["split"].astype(str))).iloc[0]
    return pd.DataFrame({
        "factor": FACTORS,
        "label": [FACTOR_LABELS[f] for f in FACTORS],
        "points": [float(d[f]) for f in FACTORS],
    }).assign(margin_change=float(d["margin_change"]))


def game_turnovers(turnovers: pd.DataFrame, game_id: str) -> pd.DataFrame:
    """Clippers turnovers in one game, in order, with what each one cost."""
    t = turnovers[(turnovers["game_id"] == game_id) & turnovers["is_team"]].sort_values("event_index")
    return pd.DataFrame({
        "half": t["period"].map(lambda p: "1st" if p <= 2 else "2nd" if p <= 4 else "OT"),
        "clock": [_period_clock(p, c) for p, c in zip(t["period"], t["clock"])],
        "player": t["player_name"].fillna("Team"),
        "type": t["sub_type"],
        "live ball": t["live_ball"].map({True: "yes", False: "no"}),
        "opponent pts off it": t["pts_off"],
        "margin before": t["margin_before"].map("{:+d}".format),
    }).reset_index(drop=True)


ZONE_ORDER = ["At the rim", "Short range", "Mid-range", "Three"]


def shot_zones(shots: pd.DataFrame, season: str) -> pd.DataFrame:
    """Shooting by zone before and after halftime: made share and attempts, in ZONE_ORDER."""
    s = shots[(shots["season"] == season) & shots["half"].isin(["H1", "H2"])]
    t = s.groupby(["zone", "half"])["made"].agg(["mean", "size"]).unstack("half")
    t.columns = [f"{a}_{b.lower()}" for a, b in t.columns]  # mean_h1, mean_h2, size_h1, size_h2
    return t.reindex([z for z in ZONE_ORDER if z in t.index]).fillna(0)


def _period_clock(period: int, seconds_left: float) -> str:
    """'Q3 7:05' (or 'OT1 0:42') from the period and seconds left on its clock."""
    name = f"Q{period}" if period <= 4 else f"OT{period - 4}"
    s = int(round(seconds_left))
    return f"{name} {s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------- players

def player_halves(player_stats: pd.DataFrame, season: str, min_minutes: float = 40) -> pd.DataFrame:
    """Season totals by half for every player with ``min_minutes`` in each half."""
    ps = player_stats[(player_stats["season"] == season) & player_stats["split"].astype(str).isin(["H1", "H2"])]
    out = summarize_players(ps.assign(split=ps["split"].astype(str)), ["player_id", "player_name", "split"])
    team_tov = out.groupby("split")["tov"].transform("sum")
    out["tov_share"] = out["tov"] / team_tov
    out["plays"] = out["fga"] + 0.44 * out["fta"] + out["tov"]
    out["play_share"] = out["plays"] / out.groupby("split")["plays"].transform("sum")
    keep = out.groupby("player_id")["minutes"].transform("min") >= min_minutes
    both = out.groupby("player_id")["split"].transform("nunique") == 2
    return out[keep & both].reset_index(drop=True)


def player_games(player_stats: pd.DataFrame, leads: pd.DataFrame, season: str, player: str) -> pd.DataFrame:
    """One row per game for one player: minutes, turnovers and TOV% in each half."""
    ps = player_stats[(player_stats["season"] == season) & (player_stats["player_name"] == player)
                      & player_stats["split"].astype(str).isin(["H1", "H2"])]
    w = ps.assign(split=ps["split"].astype(str)).pivot_table(
        index="game_id", columns="split", values=["minutes", "tov", "tov_live", "tov_pct"], aggfunc="sum")
    w.columns = [f"{stat}_{split.lower()}" for stat, split in w.columns]
    info = leads[leads["season"] == season].set_index("game_id")[
        ["game_date", "opponent_abbreviation", "result", "final_margin", "lead_class"]]
    out = info.join(w, how="inner").sort_values("game_date").reset_index()
    out["lead_class"] = out["lead_class"].map(LEAD_CLASS_LABELS)
    return out


# ----------------------------------------------------------------- league

def league_view(ranks: pd.DataFrame, season: str, metric: str, split: str) -> pd.DataFrame:
    """All 30 teams for one metric and split, best first (rank 1 = best)."""
    d = ranks[(ranks["season"] == season) & (ranks["metric"] == metric) & (ranks["split"] == split)]
    return d.sort_values("rank")[["rank", "team_name", "value", "is_team", "league_mean"]].reset_index(drop=True)


def better_direction(metric: str) -> str:
    better = METRICS.get(metric)
    return "higher is better" if better else "lower is better" if better is False else "descriptive"


def clippers_ranks(ranks: pd.DataFrame, season: str) -> pd.DataFrame:
    """The Clippers' rank on every metric in each half and on the change."""
    d = ranks[(ranks["season"] == season) & ranks["is_team"]]
    w = d.pivot(index="metric", columns="split", values="rank")[["H1", "H2", "change"]]
    w = w.reindex([m for m in METRIC_LABELS if m in w.index])
    w.index = [METRIC_LABELS.get(m, m) for m in w.index]
    return w.rename(columns={"H1": "1st half", "H2": "2nd half", "change": "change (1H to 2H)"}).astype(int)


def season_halves(game_halves: pd.DataFrame) -> pd.DataFrame:
    """Totals and rates by season and half (H1/H2), recomputed from summed counts."""
    gh = game_halves[game_halves["split"].astype(str).isin(["H1", "H2"])]
    s = summarize(gh.assign(split=gh["split"].astype(str)), ["season", "split"])
    s["tov_all"] = s["tov"] + s.get("tov_team", 0)
    s["margin"] = s["pts"] - s["opp_pts"]
    return s.set_index(["season", "split"])


PCT_METRICS = {"efg_pct", "opp_efg_pct", "oreb_pct", "opp_oreb_pct"}


def full_stat_sheet(ranks: pd.DataFrame, season: str) -> pd.DataFrame:
    """Every ranked stat for the Clippers: value and league rank in each half, and the rank of the change."""
    d = ranks[(ranks["season"] == season) & ranks["is_team"]]
    v = d.pivot(index="metric", columns="split", values="value")
    r = d.pivot(index="metric", columns="split", values="rank")
    order = [m for m in METRIC_LABELS if m in v.index]

    def fmt(m: str, x: float) -> str:
        if m in PCT_METRICS:
            return f"{x:.1%}"
        if m == "opp_ft_rate":
            return f"{x:.2f}"
        return f"{x:.1f}"

    from courtside.analysis.hypotheses import ordinal
    return pd.DataFrame([{
        "Stat": METRIC_LABELS[m], "1st half": fmt(m, v.loc[m, "H1"]), "2nd half": fmt(m, v.loc[m, "H2"]),
        "League rank, 1st half": ordinal(int(r.loc[m, "H1"])), "League rank, 2nd half": ordinal(int(r.loc[m, "H2"])),
        "Rank of the change": ordinal(int(r.loc[m, "change"])), "Better if": better_direction(m).replace(
            " is better", "").replace("descriptive", "n/a"),
    } for m in order])


def opp_ft_by_half(game_halves: pd.DataFrame) -> pd.DataFrame:
    """Opponents' free throws by season, home/road and half, with the standard error of their FT%."""
    g = game_halves[game_halves["split"].astype(str).isin(["H1", "H2"])]
    g = g.assign(split=g["split"].astype(str), where=g["is_home"].map({True: "home", False: "road"}))
    t = g.groupby(["season", "where", "split"]).agg(ftm=("opp_ftm", "sum"), fta=("opp_fta", "sum"),
                                                     games=("game_id", "nunique")).reset_index()
    t["ft_pct"] = t["ftm"] / t["fta"].where(t["fta"] > 0)
    t["se"] = (t["ft_pct"] * (1 - t["ft_pct"]) / t["fta"].where(t["fta"] > 0)) ** 0.5
    return t


# Each team's brightest brand color: a thin stripe on its game card and the "Next up" banner. Where the
# main color is too dark to see on the dark theme (Nets, Bucks, Heat, Cavaliers...) the secondary is used.
TEAM_COLORS = {
    1610612737: "#E03A3E", 1610612738: "#2E9E5B", 1610612739: "#FDBB30", 1610612740: "#C8102E",
    1610612741: "#CE1141", 1610612742: "#0B6FD0", 1610612743: "#FEC524", 1610612744: "#FFC72C",
    1610612745: "#CE1141", 1610612746: "#C8102E", 1610612747: "#FDB927", 1610612748: "#F9A01B",
    1610612749: "#EEE1C6", 1610612750: "#78BE20", 1610612751: "#FFFFFF", 1610612752: "#F58426",
    1610612753: "#0A8FDB", 1610612754: "#FDBB30", 1610612755: "#1D7DD1", 1610612756: "#E56020",
    1610612757: "#E03A3E", 1610612758: "#8E64C8", 1610612759: "#C4CED4", 1610612760: "#2E9AE0",
    1610612761: "#CE1141", 1610612762: "#F9A01B", 1610612763: "#7D97CC", 1610612764: "#E31837",
    1610612765: "#E0294A", 1610612766: "#1BA9BB",
}


def games_missing(schedule: pd.DataFrame, games: pd.DataFrame, team_id: int, now: pd.Timestamp,
                  grace_hours: float = 14) -> pd.DataFrame:
    """The team's regular-season games that tipped off over ``grace_hours`` ago but aren't in the data: the sign
    that the morning refresh hasn't run. Uses tip-off times, so a stale schedule still gives it away."""
    if schedule.empty:
        return schedule
    mine = schedule[((schedule["home_id"] == team_id) | (schedule["away_id"] == team_id))
                    & schedule["game_id"].astype(str).str.startswith("002")]
    cutoff = pd.Timestamp(now).tz_convert("UTC") - pd.Timedelta(hours=grace_hours)
    return mine[(mine["tipoff_utc"] < cutoff) & ~mine["game_id"].isin(set(games["game_id"]))]


def team_color(team_id: int) -> str:
    return TEAM_COLORS.get(int(team_id), "#898781")


def shade(hex_color: str, k: float = 0.45) -> str:
    """The color darkened toward black by ``k`` (0..1), for the deep end of a card gradient."""
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(v * (1 - k)):02x}" for v in (r, g, b))


def is_light(hex_color: str) -> bool:
    """True for pale colors (Nets white, Spurs silver, Bucks cream), which need the light-background logo."""
    r, g, b = (int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6


def logo_url(team_id: int, dark: bool = True) -> str:
    """The team's logo on the NBA's image CDN; ``dark`` is the version made for dark backgrounds."""
    return f"https://cdn.nba.com/logos/nba/{int(team_id)}/global/{'D' if dark else 'L'}/logo.svg"


def headshot_url(player_id: int, small: bool = True) -> str:
    """The player's headshot on the NBA's image CDN: 260x190 (every photo on the site shows at 74px or less),
    or the 1040x760 original with ``small=False``."""
    return f"https://cdn.nba.com/headshots/nba/latest/{'260x190' if small else '1040x760'}/{int(player_id)}.png"


def player_ids(data: DashboardData) -> dict[str, int]:
    """Every player name the dashboard can show (Clippers, opponents, defenders), to their NBA player id."""
    pairs = [data.player_box[["player_name", "player_id"]], data.history[["player_name", "player_id"]]
             if len(data.history) else None,
             data.bio[["player_name", "player_id"]] if len(data.bio) else None]
    if len(data.matchups):
        for side in ("off", "def"):
            pairs.append(data.matchups[[f"{side}_player", f"{side}_player_id"]].set_axis(
                ["player_name", "player_id"], axis=1))
    df = pd.concat([x for x in pairs if x is not None]).dropna().drop_duplicates("player_name")
    return dict(zip(df["player_name"], df["player_id"].astype(int)))


def last_names(player_box: pd.DataFrame, season: str, team: str) -> dict[str, int]:
    """Last name -> player id for one team's players this season, leaving out last names two of them share."""
    pb = player_box[(player_box["season"] == season) & (player_box["team_abbreviation"] == team)]
    roster = pb.drop_duplicates("player_id")[["player_name", "player_id"]]
    shorts = short_names(roster["player_name"])  # unique last names, or "B. Miller" when two share one
    return {shorts[n]: int(pid) for n, pid in zip(roster["player_name"], roster["player_id"])}


def names_in(text: str, full: dict[str, int], last: dict[str, int]) -> list[int]:
    """Player ids named in ``text`` (full names anywhere, the team's last names as whole words), in reading order."""
    found: dict[int, int] = {}
    rest = text
    for name in sorted(full, key=len, reverse=True):
        i = rest.find(name)
        if i >= 0 and " " in name:
            found.setdefault(full[name], i)
            rest = rest.replace(name, " " * len(name))
    for name, pid in last.items():
        m = re.search(rf"(?<![\w']){re.escape(name)}(?![\w])", rest)
        if m:
            found.setdefault(pid, m.start())
    return sorted(found, key=found.get)
