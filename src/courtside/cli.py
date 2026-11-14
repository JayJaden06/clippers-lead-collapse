"""Command-line entry point: ``courtside pull`` then ``courtside build``.

``pull`` is the only command that talks to stats.nba.com. Every later step
uses an offline client, so it can only read what ``pull`` already cached.
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

import pandas as pd
import typer
from rich.console import Console
from rich.logging import RichHandler

from courtside.analysis import hypotheses
from courtside.config import get_settings, settle_season
from courtside.nba_client import CacheMissError
from courtside.ingest import boxscores, games, injuries, league, lineups, playbyplay, players, schedule, shots, tracking
from courtside.nba_client import NBAClient
from courtside.transform import fouls, halves, leads, league_context, onoff, stints, turnovers

app = typer.Typer(help="Clippers Courtside: game reports, game plans and the second-half lead analysis.",
                  no_args_is_help=True)
console = Console()

SeasonOpt = Annotated[
    Optional[list[str]],
    typer.Option("--season", "-s", help="Season like 2026-27; repeatable. Default: both configured seasons."),
]


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Log every cache hit.")] = False) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )


def _history_seasons(settings) -> list[str]:
    from courtside.config import previous_season

    return [settings.comparison_season, previous_season(settings.comparison_season)]


def _history_people(roster: pd.DataFrame, settings) -> list:
    """Everyone on today's roster, plus any extra names in the settings (who returns is decided later)."""
    people = list(zip(roster["player_name"], roster["player_id"].astype(int)))
    on = set(roster["player_name"])
    return people + [n for n in settings.watch_players if n not in on]


@app.command()
def pull(season: SeasonOpt = None) -> None:
    """Download and cache raw stats.nba.com data (current season's log is refreshed)."""
    settings = get_settings()
    client = NBAClient(settings)
    df = games.load_games(client, settings, season, refresh_current=True)
    if not season and settle_season(settings, set(df["season"])):
        console.print(f"the new season has no games yet: staying on {settings.current_season}")
        df = games.load_games(client, settings, refresh_current=True)
    for s, n in df.groupby("season").size().items():
        console.print(f"[bold]{s}[/]: {n} completed games")
    console.print(f"game logs: {client.stats}")
    boxscores.load_boxscores(client, df, settings.quarter_seasons)
    playbyplay.load_pbp(client, df)
    pid = players.find_player_id(settings.focus_player)
    players.player_half_splits(client, pid, settings.comparison_season, settings.season_type)
    players.player_game_log(client, pid, settings.comparison_season, settings.season_type)
    with client.refreshing():  # the roster changes with trades, signings and waivers
        roster = players.team_roster(client, settings.team_id, settings.current_season)
    players.player_history(client, _history_people(roster, settings), _history_seasons(settings),
                           settings.season_type)
    _, _, skipped = tracking.load_tracking(client, df)
    waiting = [g for g in skipped if not g.startswith("gave-up:")]
    if waiting:
        console.print(f"tracking not published yet for {len(waiting)} game(s); the next pull will retry them")
    if len(waiting) < len(skipped):
        console.print(f"tracking never published for {len(skipped) - len(waiting)} older game(s); no longer retried")
    for s in sorted(df["season"].unique()):
        # Season-to-date dashboards change after every game in the current season.
        refresh = s == settings.current_season
        with client.refreshing(refresh):
            lineups.load_onoff(client, settings.team_id, s, settings.season_type)
            lineups.load_lineups(client, settings.team_id, s, settings.season_type)
            league.load_league(client, s, settings.season_type)
            tracking.load_bio(client, s, settings.season_type)
            schedule.load_player_season(client, s, settings.season_type)
            league.load_team_misc(client, s, settings.season_type)
            shots.load_shots(client, settings.team_id, s, settings.season_type)
    with client.refreshing():  # the schedule changes daily (results, times)
        sched = schedule.load_schedule(client, settings.current_season)
    report_pdf = injuries.pull_latest(settings.raw_dir)  # official.nba.com, not stats.nba.com; never fatal
    console.print(f"injury report: {report_pdf.name if report_pdf else 'not available (odds carry no injury adjustment)'}")
    played = sched[sched["game_id"].isin(set(df.loc[df["season"] == settings.current_season, "game_id"]))]
    got = injuries.pull_pregame(settings.raw_dir, played)  # once per game, then cached
    if got:
        console.print(f"pre-game injury reports: {got} new")
    console.print(f"pull done (game logs, box scores, play-by-play, {settings.focus_player}, "
                  f"on/off, lineups, league, tracking): {client.stats}")


@app.command()
def build(season: SeasonOpt = None) -> None:
    """Build processed tables from the cache (no network)."""
    settings = get_settings()
    client = NBAClient(settings, offline=True)
    try:
        df = games.load_games(client, settings, season)
    except CacheMissError:  # the calendar's new season was never pulled: pull stayed on the last one
        df = None
    if df is None or (not season and settle_season(settings, set(df["season"]))):
        if df is None:
            settle_season(settings, set())
        df = games.load_games(client, settings, season)
    games.write_games(df, settings)
    console.print(f"games: {len(df)} rows")

    team_box, player_box = boxscores.load_boxscores(client, df, settings.quarter_seasons)
    gaps = boxscores.check_split_totals(team_box)
    boxscores.write_boxscores(team_box, player_box, settings.processed_dir)
    gaps.to_csv(settings.processed_dir / "split_discrepancies.csv", index=False)
    console.print(
        f"box scores: {len(team_box)} team rows, {len(player_box)} player rows; "
        f"split totals OK ({len(gaps)} small stat corrections logged to split_discrepancies.csv)"
    )

    events = playbyplay.load_pbp(client, df)
    playbyplay.check_final_scores(events, df)
    out = settings.processed_dir

    # Turnovers and fouls from play-by-play, validated against the box scores.
    tov_events = turnovers.turnover_events(events)
    foul_events = fouls.foul_events(events)
    starts = fouls.penalty_starts(foul_events)
    agreement = fouls.check_penalty_tags(foul_events, starts)
    if agreement < 0.99:
        raise ValueError(f"penalty reconstruction agrees with official PN tags on only {agreement:.1%}")
    ft_sources = fouls.free_throw_sources(events, foul_events)
    pbp_splits = turnovers.team_turnover_splits(tov_events).merge(
        fouls.team_foul_splits(foul_events, starts, ft_sources), on=["game_id", "split"], how="outer"
    )

    game_halves = halves.build_game_halves(team_box, df, settings.team_id, pbp_splits)
    for side in ("", "opp_"):
        bad = game_halves[game_halves[f"{side}fta"] != game_halves[f"{side}fta_pbp"]]
        if not bad.empty:
            raise ValueError(f"{side}FTA from play-by-play != box score for {len(bad)} game-splits")
    halves.write_game_halves(game_halves, out)
    settings.tableau_dir.mkdir(parents=True, exist_ok=True)
    floats = game_halves.select_dtypes("float").columns
    game_halves.assign(split=game_halves["split"].astype(str)).round({c: 4 for c in floats}).to_csv(
        settings.tableau_dir / "game_halves_wide.csv", index=False
    )
    exact = {
        side: (game_halves[f"{side}pts_off_tov_est"] == game_halves[f"{side}pts_off_tov"]).mean()
        for side in ("", "opp_")
    }
    console.print(
        f"game halves: {len(game_halves)} rows; penalty tags {agreement:.2%} reconstructed; FTA match box; "
        f"points-off-TOV estimate equals the official count in {exact['opp_']:.0%} (opponent) / "
        f"{exact['']:.0%} (Clippers) of game-splits"
    )

    player_stats = turnovers.player_turnover_stats(player_box, tov_events, settings.team_id)
    turnovers.check_player_turnovers(player_stats)
    player_stats = player_stats.merge(
        fouls.player_foul_stats(foul_events), on=["game_id", "player_id", "split"], how="left"
    )
    foul_cols = ["fouls_shooting", "fouls_offensive", "fouls_late_trailing"]
    player_stats[foul_cols] = player_stats[foul_cols].fillna(0).astype(int)
    player_stats.to_parquet(out / "player_half_stats.parquet", index=False)
    player_stats.round(4).to_csv(out / "player_half_stats.csv", index=False)
    player_stats.round(4).to_csv(settings.tableau_dir / "player_half_stats.csv", index=False)
    tov_events.to_parquet(out / "turnover_events.parquet", index=False)
    foul_events.drop(columns=["description"]).to_parquet(out / "foul_events.parquet", index=False)

    pid = players.find_player_id(settings.focus_player)
    baselines = turnovers.focus_player_baselines(
        player_stats,
        players.player_half_splits(client, pid, settings.comparison_season, settings.season_type),
        players.player_game_log(client, pid, settings.comparison_season, settings.season_type),
        pid, settings.comparison_season, settings.team_abbreviation,
    )
    baselines.round(4).to_csv(out / "focus_player_baselines.csv", index=False)
    roster = players.team_roster(client, settings.team_id, settings.current_season)
    roster.to_parquet(out / "roster.parquet", index=False)
    history = players.player_history(client, _history_people(roster, settings), _history_seasons(settings),
                                     settings.season_type)
    history.to_parquet(out / "player_history_halves.parquet", index=False)
    history.round(4).to_csv(out / "player_history_halves.csv", index=False)
    console.print(
        f"players: {len(player_stats)} player-split rows (TOV types match box); "
        f"{settings.focus_player} baselines for {len(baselines[['season', 'team']].drop_duplicates())} team-seasons"
    )

    series = leads.margin_series(events)
    game_leads = leads.game_leads(
        series, df, settings.lead_threshold, settings.lead_window_minutes, settings.sensitivity_thresholds
    )
    leads.check_halftime_margins(game_leads, game_halves)
    leads.write_leads(series, game_leads, out)
    console.print(
        f"play-by-play: {len(events)} events; final scores and halftime margins match box scores; "
        f"{len(game_leads)} games classified"
    )

    # Who was on the floor (seasons with per-quarter box scores), and the plays behind each game report.
    segments = stints.build_segments(events, player_box, df, settings.team_id, settings.quarter_seasons)
    seg_check = stints.check_segments(segments, player_box)
    segments.to_parquet(out / "segments.parquet", index=False)
    play_cols = ["game_id", "season", "event_index", "period", "clock", "elapsed", "team_id", "person_id",
                 "player_name", "action_type", "sub_type", "description", "shot_value", "shot_result",
                 "team_score", "opp_score", "margin", "is_team"]
    events[events["season"].isin(settings.quarter_seasons)][play_cols].to_parquet(out / "plays.parquet", index=False)
    console.print(
        f"on court: {len(segments)} segments; minutes match the box score for {seg_check['minutes_match']:.1%} "
        f"of player-games, plus-minus for {seg_check['plus_minus_match']:.1%}"
    )

    seasons = sorted(df["season"].unique())
    onoff_raw = pd.concat([lineups.load_onoff(client, settings.team_id, s, settings.season_type) for s in seasons])
    lineup_raw = pd.concat([lineups.load_lineups(client, settings.team_id, s, settings.season_type) for s in seasons])
    league_raw = pd.concat([league.load_league(client, s, settings.season_type) for s in seasons])
    onoff.check_onoff_minutes(onoff_raw)
    onoff.check_lineup_minutes(lineup_raw, onoff_raw)
    league_context.check_against_box(league_raw, game_halves, settings.team_id)
    onoff_h = onoff.onoff_halves(onoff_raw)
    lineup_h = onoff.lineup_halves(lineup_raw)
    ranks = league_context.half_ranks(league_raw, settings.team_id)
    for name, frame in (("onoff_halves", onoff_h), ("lineup_halves", lineup_h), ("league_half_ranks", ranks),
                        ("league_periods", league_raw)):
        frame.to_parquet(out / f"{name}.parquet", index=False)
        frame.round(4).to_csv(out / f"{name}.csv", index=False)
    ranks.round(4).to_csv(settings.tableau_dir / "league_half_ranks.csv", index=False)
    console.print(
        f"on/off: {len(onoff_h)} rows; lineups: {lineup_h['group_id'].nunique()} lineups (minutes add up); "
        f"league ranks: {len(ranks)} rows (team totals match box scores)"
    )

    matchups, hustle, skipped = tracking.load_tracking(client, df)
    coverage = tracking.check_matchups(matchups, player_box)
    bio = pd.concat([tracking.load_bio(client, s, settings.season_type) for s in seasons], ignore_index=True)
    for name, frame in (("matchups", matchups), ("hustle", hustle), ("player_bio", bio)):
        frame.to_parquet(out / f"{name}.parquet", index=False)
        frame.round(4).to_csv(out / f"{name}.csv", index=False)
    sched = schedule.load_schedule(client, settings.current_season)
    player_season = pd.concat([schedule.load_player_season(client, s, settings.season_type) for s in seasons],
                              ignore_index=True)
    sched.to_parquet(out / "schedule.parquet", index=False)
    pd.concat([league.load_team_misc(client, s, settings.season_type) for s in seasons],
              ignore_index=True).to_parquet(out / "team_misc.parquet", index=False)
    player_season.to_parquet(out / "player_season.parquet", index=False)
    shot_table = pd.concat([shots.load_shots(client, settings.team_id, s, settings.season_type) for s in seasons],
                           ignore_index=True)
    shot_table = shot_table[shot_table["game_id"].isin(set(df["game_id"]))]  # games we have box scores for
    shot_table.to_parquet(out / "shots.parquet", index=False)
    _write_injuries(settings, out, sched)
    console.print(
        f"tracking: {matchups['game_id'].nunique()} games of matchups and hustle "
        f"({len(skipped)} not published yet), matchups cover {coverage:.0%} of points; bio for {len(bio)} players"
    )
    console.print(f"wrote to {settings.processed_dir}")



def _write_injuries(settings, out, sched: pd.DataFrame | None = None) -> None:
    """The newest injury report's rows for Clippers games (``injuries``), and each played game's last pre-game
    report (``game_injuries``). Rewritten only when a player or status changes, so a report that says the same
    thing as the last one isn't news for the morning refresh."""
    if sched is not None and len(sched):
        try:
            pre = injuries.pregame_table(settings.raw_dir)
            match = sched.assign(matchup=sched["away"] + "@" + sched["home"])[["game_id", "matchup"]]
            pre = pre.merge(match, on=["game_id", "matchup"], how="inner")  # each report's rows for its own game
            path = out / "game_injuries.parquet"
            if not (path.exists() and injuries.same_rows(pd.read_parquet(path), pre, extra=["game_id"])):
                pre.to_parquet(path, index=False)
                console.print(f"pre-game injury reports: {pre['game_id'].nunique()} games")
        except Exception as e:
            console.print(f"[yellow]pre-game injury reports not read ({type(e).__name__}: {e})[/]")
    try:
        table = injuries.team_table(settings.raw_dir, settings.team_abbreviation)
    except Exception as e:  # a report in a new layout shouldn't stop the rest of the build
        console.print(f"[yellow]injury report not read ({type(e).__name__}: {e}); keeping the previous one[/]")
        return
    if table is None:
        console.print("injury report: none cached yet")
        return
    path = out / "injuries.parquet"
    if path.exists() and injuries.same_rows(pd.read_parquet(path), table):
        console.print("injury report: no change for Clippers games")
        return
    table.to_parquet(path, index=False)
    console.print(f"injury report: {len(table)} players listed for Clippers games")


def _analysis_meta(settings, inp: hypotheses.Inputs) -> dict:
    from datetime import date

    return {
        "season": settings.current_season, "comparison_season": settings.comparison_season,
        "games": inp.n_games, "focus_player": settings.focus_player, "team": settings.team_abbreviation,
        "analyzed_on": date.today().isoformat(), "lead_threshold": settings.lead_threshold,
    }


def _load_inputs(settings) -> hypotheses.Inputs:
    built = settings.processed_dir / "games.parquet"
    if built.exists():
        settle_season(settings, set(pd.read_parquet(built, columns=["season"])["season"]))
    return hypotheses.load_inputs(
        settings.processed_dir, settings.current_season, settings.comparison_season, settings.focus_player
    )


@app.command()
def analyze() -> None:
    """Run the hypothesis tests on the processed tables (no network)."""
    settings = get_settings()
    inp = _load_inputs(settings)
    results = hypotheses.run_all(inp)
    meta = _analysis_meta(settings, inp)
    hypotheses.write_results(results, settings.processed_dir / "analysis", settings.reports_dir / "analysis.json", meta)
    for r in results:
        answer = r.verdict.split(":")[0] if len(r.verdict.split(":")[0]) < 20 else r.verdict.split(".")[0]
        console.print(f"[bold]{r.id}[/] {r.title} -> {answer}")
    console.print(f"wrote {settings.reports_dir / 'analysis.json'} and {settings.processed_dir / 'analysis'}/")


@app.command()
def report() -> None:
    """Draw the figures and write reports/findings.md (no network)."""
    import json

    from courtside.analysis import report as report_mod

    settings = get_settings()
    inp = _load_inputs(settings)
    results = hypotheses.run_all(inp)
    meta = _analysis_meta(settings, inp)
    saved = settings.reports_dir / "analysis.json"
    if saved.exists():
        # Keep the date of the analysis the numbers came from, so rerunning the report changes nothing.
        meta["analyzed_on"] = json.loads(saved.read_text(encoding="utf-8"))["meta"].get("analyzed_on",
                                                                                       meta["analyzed_on"])
    margins = pd.read_parquet(settings.processed_dir / "margin_series.parquet")
    path = report_mod.write_report(results, inp, meta, margins, settings.reports_dir)
    console.print(f"wrote {path} and {settings.figures_dir}/")


@app.command("all")
def run_all(
    season: SeasonOpt = None,
    offline: Annotated[bool, typer.Option("--offline", help="Skip `pull` and rebuild from the cache.")] = False,
) -> None:
    """pull -> build -> analyze -> report. Safe to rerun: cached responses are reused."""
    if not offline:
        pull(season)
    build(season)
    analyze()
    report()


@app.command()
def dashboard(port: Annotated[int, typer.Option(help="Port for the local Streamlit server.")] = 8501) -> None:
    """Open the Streamlit dashboard (install the dashboard extra first; see the README)."""
    import subprocess
    import sys
    from importlib.util import find_spec

    from courtside.config import PROJECT_ROOT

    if find_spec("streamlit") is None:
        console.print(r'[red]Streamlit is not installed.[/] Run: pip install -e ".\[dashboard]"')
        raise typer.Exit(1)
    app_path = PROJECT_ROOT / "dashboard" / "app.py"
    raise typer.Exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path),
                                      "--server.port", str(port)]))
