"""Games: the intro, the Next up banner, every played game's report and every upcoming game's plan.
"""

from __future__ import annotations

import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from courtside.analysis import availability as A
from courtside.analysis import gameplan as GP
from courtside.analysis import gamereport as R
from courtside.analysis import preview as P
from courtside.analysis.hypotheses import ordinal
from courtside.names import short
from courtside.viz import dashboard_data as D
from courtside.viz import graphics as G
from courtside.viz import story as S
from courtside.viz import whatnow as W
from courtside.web.context import current
from courtside.web.theme import BAD, BG, FOCUS, GOOD, GRAY, H1C, H2C, INK_MARK, LIGHT, MUTED_BAR, TONE_COLOR, _minus, signed
from courtside.web.ui import PHOTO_COL, answer_cards, clicked, face, fill_toc, heading, page_top, picture, section, show, with_photos


def _step_game(key: str, labels: list[str], step: int) -> None:
    """Previous / next game buttons."""
    cur = st.session_state.get(key, labels[-1])
    i = labels.index(cur) if cur in labels else len(labels) - 1
    st.session_state[key] = labels[max(0, min(len(labels) - 1, i + step))]


def _set_game(key: str, label: str) -> None:
    st.session_state[key] = label


def _upcoming(season: str) -> tuple[pd.DataFrame, list, pd.DataFrame, float | None]:
    """Games left this season, their previews, the team table, and the season's second-half shooting cost."""
    ctx = current()
    data = ctx.data
    season_now = ctx.season_now
    season_prev = ctx.season_prev
    settings = ctx.settings
    if season != season_now or data.schedule.empty or data.league_periods.empty:
        return pd.DataFrame(), [], pd.DataFrame(), None
    teams = P.blended(P.team_table(data.league_periods, season_now), P.team_table(data.league_periods, season_prev))
    att = data.attribution.get(season_now)
    shooting = float(att.set_index("factor").loc["shooting", "per_game"]) if att is not None else None
    tid = settings.team_id
    up = data.schedule[((data.schedule["home_id"] == tid) | (data.schedule["away_id"] == tid))
                       & (data.schedule["status"] < 3)].sort_values("tipoff_utc").reset_index(drop=True)
    # the injury report: who may sit, and what it's worth (analysis.availability)
    values = A.player_values(data.player_season, data.league_periods, season_now, season_prev)
    names_ = teams.set_index("team_id")["team_name"]
    previews = []
    for _, g in up.iterrows():
        opp_tid = int(g["away_id"] if int(g["home_id"]) == tid else g["home_id"])
        day = g["tipoff_utc"].tz_convert("America/New_York").normalize().tz_localize(None)
        matchup = f"{g['away']}@{g['home']}"
        team_out = A.missing(data.injuries, values, day, matchup, names_.get(tid, ""))
        opp_out = A.missing(data.injuries, values, day, matchup, names_.get(opp_tid, ""))
        pv = P.preview(g, teams, tid, shooting, injury_edge=A.edge(team_out, opp_out))
        pv.injury_report, pv.team_out, pv.opp_out = A.has_report(data.injuries, day, matchup), team_out, opp_out
        previews.append(pv)
    return up, previews, teams, shooting


def _hide_intro() -> None:
    st.session_state["intro_hidden"] = True


def intro() -> None:
    """The welcome at the top of the landing page, in its light band."""
    with st.container(key="band_light_intro"):
        _intro()


def _intro() -> None:
    """What this is, and one live tile per page."""
    ctx = current()
    data = ctx.data
    season_now = ctx.season_now
    g = data.games[data.games["season"] == season_now]
    wins, losses = int((g["result"] == "W").sum()), int((g["result"] == "L").sum())
    last = pd.to_datetime(g["game_date"]).max()
    lc = data.game_leads.loc[data.game_leads["season"] == season_now, "lead_class"]
    blown, leads = int((lc == "blown_lead").sum()), int(lc.isin(["blown_lead", "held_lead"]).sum())
    hl = (S.headline(data.analysis, data.comparison, data.games, season_now)
          if not data.comparison.empty and season_now in set(data.comparison["season"]) else None)
    h1, h2 = (hl["h1_per_game"], hl["h2_per_game"]) if hl else (np.nan, np.nan)
    ph = D.player_halves(data.player_stats, season_now)
    top = ph[ph["split"] == "H2"].sort_values("tov_share").iloc[-1] if len(ph) else None
    rk = data.ranks[(data.ranks["season"] == season_now) & data.ranks["is_team"]
                    & (data.ranks["metric"] == "net_rtg") & (data.ranks["split"] == "H2")]["rank"]

    tiles = [("games-list", "Games", f"{wins}-{losses}",
              "Pick any game below: a report for each one played, a game plan for each one coming up.",
              None, None, "info")]
    if leads:
        tiles.append(("answer", "Blown leads", f"{blown} of {leads}",
                      "early leads they let slip. Why the second half goes wrong.", ("dots", blown, leads), None,
                      "bad" if blown * 2 >= leads else "info"))
    if not np.isnan(h2):
        tiles.append(("what-now", "What now?", f"{signed(h2)} per game",
                      "after halftime. What the numbers say has to change.",
                      ("pair", h1, h2, "1st half", "2nd half"), None, "bad" if h2 < h1 else "good"))
    if top is not None:
        tiles.append(("players", "Players", top["player_name"],
                      f"makes {top['tov_share']:.0%} of the turnovers after halftime. Who else, and how.",
                      None, D.headshot_url(int(top["player_id"])), "warn"))
    if len(rk):
        r = int(rk.iloc[0])
        tiles.append(("league", "Vs. the league", f"{ordinal(r)} of 30",
                      "in the second half. How every team changes after halftime.", ("rank", r, 30), None,
                      "bad" if r > 20 else "good" if r <= 10 else "warn"))

    st.markdown(f'<div class="kicker">LA Clippers · {season_now} season · updated through {last:%b} {last.day}'
                '</div><div class="hero">Clippers Courtside</div>'
                '<div class="lede">A fan-made tracker of the Clippers\' season, built from the NBA\'s own play-by-play '
                'data. It began with one question (why do they keep losing leads after halftime?) and now follows '
                'every game. It updates the morning after each game. Start anywhere:</div>',
                unsafe_allow_html=True)
    html = "".join(
        f'<a class="vcard" href="{"#" + slug if slug == "games-list" else slug}" target="_self">'
        + (f'<img class="v-img" src="{img}" alt="" loading="lazy">' if img else "")
        + f'<div class="v-title"><span class="v-dot" style="background:{TONE_COLOR.get(tone, GRAY)}"></span>'
          f'{title}</div><div class="v-big">{_minus(big)}</div>'
        + (f'<div class="v-mini">{G.mini(viz, tone)}</div>' if viz else "")
        + f'<div class="v-small">{small}</div></a>'
        for slug, title, big, small, viz, img, tone in tiles)
    st.markdown(f'<div class="vcards intro">{html}</div>', unsafe_allow_html=True)
    left, right = st.columns([5, 1], vertical_alignment="center")
    with left:
        with st.expander("How it works"):
            st.markdown(
                "- **Data:** every play of every Clippers game, pulled from stats.nba.com with the open-source "
                "[nba_api](https://github.com/swar/nba_api) package, compared with last season and the rest of "
                "the league.\n"
                "- **Updates:** each morning, a refresh pulls the newest games and reruns everything. Every page "
                "and every number moves with it.\n"
                "- **Odds** for upcoming games come from a simple team-strength model: no injuries, rest or "
                "betting lines.\n"
                "- Not affiliated with the NBA or the Clippers. Words you don't know? Try the "
                "**What do these words mean?** button.")
    right.button("Hide intro", icon=":material/close:", on_click=_hide_intro, width="stretch", type="tertiary")


COURT_LINES = ('<svg class="court" viewBox="0 0 760 300" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" '
               'fill="none" stroke="#ffffff" stroke-width="4"><rect x="2" y="2" width="756" height="296" rx="6"/>'
               '<line x1="380" y1="2" x2="380" y2="298"/><circle cx="380" cy="150" r="45"/>'
               '<rect x="2" y="95" width="150" height="110"/><rect x="608" y="95" width="150" height="110"/>'
               '<circle cx="152" cy="150" r="45"/><circle cx="608" cy="150" r="45"/>'
               '<path d="M2 30 L50 30 A140 140 0 0 1 50 270 L2 270"/>'
               '<path d="M758 30 L710 30 A140 140 0 0 0 710 270 L758 270"/></svg>')


def _future_label(t: pd.Timestamp, pv, j: int) -> str:
    """How an upcoming game reads in the game picker (the banner's button opens it by this label)."""
    return (f"{t:%b} {t.day} · {'vs' if pv.home else '@'} {pv.opponent} · "
            f"{'next game, ' if j == 0 else ''}{pv.chance:.0%} to win")


def next_up(box, up: pd.DataFrame, previews: list, teams: pd.DataFrame, shooting: float | None) -> None:
    """The next game as a banner: both logos, when and where, the win chance, and the top key to it."""
    ctx = current()
    data = ctx.data
    season_now = ctx.season_now
    settings = ctx.settings
    if not previews:
        return
    pv, g = previews[0], up.iloc[0]
    t = g["tipoff_utc"].tz_convert("America/Los_Angeles")
    opp_id = int(g["away_id"] if pv.home else g["home_id"])
    players = GP.player_table(data.player_box, season_now, settings.team_abbreviation)
    misc = data.team_misc[data.team_misc["season"] == season_now] if len(data.team_misc) else pd.DataFrame(
        columns=["team_id", "opp_pts_paint"])
    keys = GP.game_plan(pv, teams, misc, players, shooting)
    key = (f'<div class="nu-key">The key: <b>{keys[0].title}</b>, worth about {signed(keys[0].points)} a game. '
           f'{keys[0].why}</div>') if keys else ""
    when = f"{t:%a %b} {t.day} · {t:%I:%M %p}".replace(" 0", " ") + f" PT · {pv.arena}"
    with box:
        st.markdown(
            f'<div class="nextup" style="--opp:{D.team_color(opp_id)}">{COURT_LINES}'
            f'<div class="nu-kicker">Next up · {when}</div>'
            f'<div class="nu-row"><img src="{D.logo_url(settings.team_id)}" alt="Clippers">'
            f'<span class="nu-at">{"vs" if pv.home else "@"}</span><img src="{D.logo_url(opp_id)}" alt="">'
            f'<span class="nu-name">{pv.opponent_name}</span>'
            f'<div class="nu-chance"><b>{pv.chance:.0%}</b><span>chance to win</span></div></div>{key}</div>',
            unsafe_allow_html=True)
        st.button("Open the game plan", icon=":material/sports_basketball:", key="open_next_up",
                  on_click=_set_game, args=(f"pick_{season_now}", _future_label(t, pv, 0)))


def _unit_rows(units, names: dict) -> str:
    """The outscored five-man units as rows (faces, the five names, the score and minutes) instead of one run-on
    sentence."""
    ids = {v: k for k, v in names.items()}
    return "".join(
        '<div class="u-row"><div class="u-faces">'
        + "".join(f'<img src="{D.headshot_url(ids[n], small=True)}" alt="" title="{n}" loading="lazy">'
                  for n in unit if n in ids)
        + f'</div><div class="u-pm">{signed(pm, 0)}</div><div class="u-min">{mins:.0f} min</div>'
        f'<div class="u-who">{", ".join(short(n) for n in unit)}</div></div>'
        for unit, pm, mins in units)


def page_replay() -> None:
    ctx = current()
    data = ctx.data
    focus = ctx.focus
    focus_last = ctx.focus_last
    season_now = ctx.season_now
    settings = ctx.settings
    if not st.session_state.get("intro_hidden"):
        intro()
        st.markdown('<div id="games-list"></div>', unsafe_allow_html=True)
    banner = st.container()
    hidden = bool(st.session_state.get("intro_hidden"))
    page_top("Games", "Every game this season: the report for games played, the game plan for games coming up. "
             "Updates after each game.", show_kicker=hidden, band=hidden)
    leads = data.game_leads.set_index("game_id")
    g_all = data.games.set_index("game_id")
    season = st.session_state.get("game_season", data.seasons[0])
    if season not in data.seasons:
        season = data.seasons[0]
    options = D.game_options(data.game_leads, season).iloc[::-1].reset_index(drop=True)  # oldest first
    strip = leads.loc[options["game_id"]].reset_index()
    gi = g_all.reindex(strip["game_id"])
    entries = [{"kind": "past", "gid": g, "date": pd.Timestamp(d), "home": bool(h), "opp": o, "opp_id": int(oid),
                "status": f"{r} {int(tp)}-{int(op)}", "won": r == "W",
                "label": f"{pd.Timestamp(d):%b} {pd.Timestamp(d).day} · {'vs' if h else '@'} {o} · {r} {int(tp)}-{int(op)}"}
               for g, d, h, o, oid, r, tp, op in zip(strip["game_id"], gi["game_date"], gi["is_home"],
                                                     gi["opponent_abbreviation"], gi["opponent_id"], gi["result"],
                                                     gi["team_pts"], gi["opp_pts"])]
    up, previews, teams, shooting = _upcoming(season)
    for j, (pv, (_, g)) in enumerate(zip(previews, up.iterrows())):
        t = g["tipoff_utc"].tz_convert("America/Los_Angeles")
        entries.append({"kind": "future", "idx": j, "date": t, "home": pv.home, "opp": pv.opponent,
                        "opp_id": int(g["away_id"] if pv.home else g["home_id"]), "status": f"{pv.chance:.0%} to win",
                        "won": None, "label": _future_label(t, pv, j)})
    if season == season_now:
        next_up(banner, up, previews, teams, shooting)
    labels = [e["label"] for e in entries]
    n_past = len(strip)
    xs = pd.to_datetime(strip["game_date"]).dt.strftime("%b %d").str.replace(" 0", " ") + " " + strip[
        "opponent_abbreviation"]
    by_x = dict(zip(xs, labels[:n_past]))
    pick_key = f"pick_{season}"
    st.session_state.setdefault(pick_key, labels[n_past - 1] if n_past else labels[0])  # the latest result
    jump = st.session_state.pop("jump_game", None)
    if jump in set(strip["game_id"]):
        st.session_state[pick_key] = labels[list(strip["game_id"]).index(jump)]
    x = clicked(st.session_state.get(f"strip_{season}"), "x", f"strip_click_{season}")  # a click on the strip
    if x in by_x:
        st.session_state[pick_key] = by_x[x]
    if st.session_state[pick_key] not in labels:
        st.session_state[pick_key] = labels[n_past - 1] if n_past else labels[0]

    # ---- the game picker: pinned to the top of the page while scrolling
    with st.container(key="gamebar"):
        c_season, c_prev, c_pick, c_next, c_logo = st.columns([1.2, 0.45, 4, 0.45, 0.5], vertical_alignment="bottom",
                                                                gap="small")
        c_season.selectbox("Season", data.seasons, key="game_season")
        c_prev.button("◀", key="prev_game", on_click=_step_game, args=(pick_key, labels, -1), help="Previous game",
                      width="stretch")
        pick = c_pick.selectbox("Game", labels, key=pick_key)
        c_next.button("▶", key="next_game", on_click=_step_game, args=(pick_key, labels, 1), help="Next game",
                      width="stretch")
        idx = labels.index(pick)
        entry = entries[idx]
        c_logo.image(D.logo_url(entry["opp_id"], dark=False), width=46)
        nav_ = st.container()  # the On this page pills, filled once the report or plan is drawn

    # ---- the schedule around this game: played games and the ones coming up
    lo = max(0, min(idx - 3, len(entries) - 7))
    window = entries[lo:lo + 7]
    cols = st.columns(len(window), gap="small")
    for k, (col, e) in enumerate(zip(cols, window), start=lo):
        sel = k == idx
        with col.container(border=True, key="gcard_sel" if sel else f"gcard_{k}"):
            oc = D.team_color(e["opp_id"])
            st.markdown(f'<div class="gm" style="--opp:{oc}"><img class="lac" src="{D.logo_url(settings.team_id)}" '
                        f'alt="Clippers"><img class="opp" src="{D.logo_url(e["opp_id"], dark=not D.is_light(oc))}" '
                        f'alt="{e["opp"]}"></div>', unsafe_allow_html=True)
            color = GOOD if e["won"] else BAD if e["won"] is False else INK_MARK
            st.markdown(f'<div class="gc"><div class="gc-date">{e["date"]:%a %b} {e["date"].day}</div>'
                        f'<div class="gc-opp">{"vs" if e["home"] else "@"} {e["opp"]}</div>'
                        f'<div class="gc-status" style="color:{color}">{e["status"]}</div></div>',
                        unsafe_allow_html=True)
            st.button("Showing" if sel else ("Report" if e["kind"] == "past" else "Game plan"), key=f"open_{k}",
                      on_click=_set_game, args=(pick_key, e["label"]), disabled=sel, width="stretch")

    if entry["kind"] == "future":
        _game_plan(up.iloc[entry["idx"]], previews[entry["idx"]], teams, shooting)
        fill_toc(nav_)
        return

    gid = entry["gid"]
    row = leads.loc[gid]
    where = "Home, Intuit Dome" if bool(g_all.loc[gid, "is_home"]) else "Away"
    st.markdown(f'<div class="kicker">{pd.Timestamp(row["game_date"]):%A, %B} {pd.Timestamp(row["game_date"]).day} · '
                f'{where}</div>', unsafe_allow_html=True)

    with st.expander("Season at a glance: every game from halftime to the final (click one to open it)"):
        fig = go.Figure()
        for xx, h, f, blown in zip(xs, strip["halftime_margin"], strip["final_margin"],
                                   strip["lead_class"] == "blown_lead"):
            fig.add_trace(go.Scatter(x=[xx, xx], y=[h, f], mode="lines",
                                     line=dict(color=BAD if blown else LIGHT, width=3), hoverinfo="skip",
                                     showlegend=False))
        fig.add_trace(go.Scatter(x=xs, y=strip["halftime_margin"], mode="markers", name="At halftime",
                                 marker=dict(color=H1C, size=11, line=dict(color=BG, width=1.5)),
                                 hovertemplate="%{x}<br>At halftime: %{y:+d}<extra></extra>"))
        fig.add_trace(go.Scatter(x=xs, y=strip["final_margin"], mode="markers", name="Final",
                                 marker=dict(color=H2C, size=11, symbol="diamond", line=dict(color=BG, width=1.5)),
                                 hovertemplate="%{x}<br>Final: %{y:+d}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=GRAY, width=1))
        if len(strip) > 20:
            fig.update_xaxes(showticklabels=False)
        show(fig, 230, key=f"strip_{season}", select=True, yaxis_title="Clippers margin")
        st.caption("Halftime (●) to final (◆). Orange = a blown early lead.")

    halves = data.game_halves[(data.game_halves["game_id"] == gid)
                              & data.game_halves["split"].astype(str).isin(["H1", "H2"])]
    att = D.game_attribution(data.game_halves, gid)
    mq = D.game_margin(data.margins, gid).groupby("period")[["team_score", "opp_score"]].max()
    team_q = mq["team_score"].diff().fillna(mq["team_score"]).astype(int).tolist()
    opp_q = mq["opp_score"].diff().fillna(mq["opp_score"]).astype(int).tolist()
    opp = row["opponent_abbreviation"]
    names = data.player_box.drop_duplicates("player_id").set_index("player_id")["player_name"].to_dict()
    lines = R.player_lines(data.player_box, gid, "LAC")
    opp_lines = R.player_lines(data.player_box, gid, opp)
    factors = R.vs_normal(data.game_halves, gid)
    seg = data.segments[data.segments["game_id"] == gid] if len(data.segments) else pd.DataFrame()
    game_units = R.units(seg, names)
    plays = data.plays[data.plays["game_id"] == gid] if len(data.plays) else pd.DataFrame()
    run_against, run_for = R.biggest_runs(data.margins, gid)
    if len(plays) and len(seg):
        run_against = R.describe_run(run_against, plays, seg, names) if run_against else None
        run_for = R.describe_run(run_for, plays, seg, names) if run_for else None
    game_def = R.defenders_for_game(data.matchups, gid, "LAC") if len(data.matchups) else pd.DataFrame()
    sbox = data.player_box[(data.player_box["season"] == season) & (data.player_box["team_abbreviation"] == "LAC")
                           & (data.player_box["split"].astype(str) == "FULL")].groupby("player_name")[
        ["minutes", "fga", "fta", "tov", "oreb", "dreb", "fgm", "fg3m"]].sum().reset_index()
    sd_ = W.defenders(data.matchups, data.hustle, data.bio, season, "LAC") if len(data.matchups) and len(
        data.bio) else None
    season_def = sd_.table if sd_ is not None else None
    lvs = R.levers(factors, lines, sbox, game_def, season_def, game_units) if len(factors) else []

    # ---- the result
    opp_id_ = int(g_all.loc[gid, "opponent_id"])
    # the scoreboard is its own white card, so it skips the panel padding and runs the full width
    st.markdown(G.scoreboard("LAC", opp, team_q, opp_q, row["final_margin"] > 0,
                             team_logo=D.logo_url(settings.team_id, dark=False),
                             opp_logo=D.logo_url(opp_id_, dark=False), team_color="#1d428a",
                             opp_color=D.team_color(opp_id_)).replace('<div class="gfx">',
                                                                      '<div class="gfx" style="padding:0">', 1),
                unsafe_allow_html=True)
    with st.container(border=True):
        tag = S.LEAD_TAG.get(row["lead_class"], "")
        if tag:
            st.badge(tag, color="orange" if row["lead_class"] == "blown_lead" else "blue")
        st.markdown(f'<div class="story">{S.game_story(row, halves, att)}</div>', unsafe_allow_html=True)
        if len(factors):
            st.markdown(f'<div class="takeaway"><b>{R.verdict(factors, lvs)}</b></div>', unsafe_allow_html=True)

    # ---- the tiles: best, worst, the runs, turnovers
    best, worst = R.best_and_worst(lines)
    tiles = []
    for who, title, tone in ((best, "Best Clipper", "good"), (worst, "Toughest night", "bad")):
        if who is not None:
            tiles.append(W.Verdict(
                f"{title}: {who['player_name']}", f"{who['game_score']:.1f}",
                f"Game Score. {int(who['pts'])} pts, {int(who['reb'])} reb, {int(who['ast'])} ast, "
                f"{int(who['tov'])} TO in {who['minutes']:.0f} min; {signed(who['plus_minus'], 0)} on the floor.",
                tone, "players"))
    for run, title, tone in ((run_against, f"Biggest {opp} run", "bad"), (run_for, "Biggest Clippers run", "good")):
        if run is not None:
            who = ", ".join(short(n) for n in run.unit) if run.unit else "?"
            tiles.append(W.Verdict(title, run.label, f"{R.run_window(run)}. On the floor: {who}.", tone, "runs",
                                   ("diverge", (run.team_pts, -run.opp_pts), ("LAC", opp))))
    tiles.append(S.game_cards(row, halves, data.turnovers, focus_last)[-1])
    answer_cards(tiles)

    # ---- the replay, with the runs shaded
    heading("How it played out", "runs")
    m = D.game_margin(data.margins, gid)
    end = max(48.0, float(m["minute"].max()))
    blown = row["lead_class"] == "blown_lead"
    line_color = BAD if blown else H1C
    show_tov = st.toggle("Show Clippers turnovers on the chart", value=True,
                         help=f"Orange diamonds are {focus}'s turnovers; gray circles are everyone else's.")
    fig = go.Figure()
    for run, color in ((run_against, "rgba(217,89,38,0.16)"), (run_for, "rgba(57,135,229,0.16)")):
        if run is not None:
            fig.add_vrect(x0=run.start / 60, x1=run.end / 60, fillcolor=color, line_width=0, layer="below",
                          annotation_text=("LAC " if not run.against else f"{opp} ") + run.label,
                          annotation_position="top left", annotation_font_size=12)
    fig.add_vline(x=24, line=dict(color=GRAY, width=1, dash="dot"))
    fig.add_hline(y=0, line=dict(color=GRAY, width=1))
    custom = np.column_stack([m["team_score"], m["opp_score"], m["period"]])
    fig.add_trace(go.Scatter(x=m["minute"], y=m["margin"], mode="lines", line=dict(color=LIGHT, width=1.5, shape="hv"),
                             hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(
        x=m["minute"], y=m["margin"], mode="lines", line=dict(color=line_color, width=2.5, shape="hv"),
        customdata=custom, name="Clippers margin",
        hovertemplate="Minute %{x:.1f}<br>LAC %{customdata[0]} – " + opp + " %{customdata[1]}"
                      "<br>Margin %{y:+d}<extra></extra>"))
    if show_tov:
        tm = S.turnover_markers(data.turnovers, data.margins, gid, focus_last)
        for is_focus, name, symbol, color, size in ((False, "Other turnovers", "circle", GRAY, 9),
                                                    (True, f"{focus_last} turnovers", "diamond", FOCUS, 12)):
            sub = tm[tm["is_focus"] == is_focus]
            fig.add_trace(go.Scatter(
                x=sub["minute"], y=sub["margin"], mode="markers", name=name,
                marker=dict(symbol=symbol, color=color, size=size, line=dict(color=BG, width=1.2)),
                customdata=np.column_stack([sub["who"], sub["sub_type"], sub["kind"], sub["pts_off"]]),
                hovertemplate="<b>%{customdata[0]}</b>: %{customdata[1]}<br>%{customdata[2]}"
                              "<br>Opponent scored %{customdata[3]} off it<extra></extra>"))
    stops = S.replay_frames(m, step_seconds=60)
    frames = []
    for t in stops:
        cut = m[m["minute"] <= t]
        last = cut.iloc[-1] if len(cut) else m.iloc[0]
        frames.append(go.Frame(
            name=f"{t:.1f}", traces=[1],
            data=[go.Scatter(x=cut["minute"], y=cut["margin"], customdata=custom[: len(cut)])],
            layout=dict(title=dict(text=f"Minute {t:.0f} · LAC {int(last['team_score'])} – "
                                        f"{opp} {int(last['opp_score'])}"))))
    fig.frames = frames
    fig.update_layout(
        title=dict(text=f"Final · LAC {int(m['team_score'].iloc[-1])} – {opp} {int(m['opp_score'].iloc[-1])}",
                   x=0, font=dict(size=15)),
        updatemenus=[dict(type="buttons", showactive=False, x=1, xanchor="right", y=1.18, direction="left", buttons=[
            dict(label="▶ Replay", method="animate",
                 args=[None, dict(frame=dict(duration=25, redraw=True), transition=dict(duration=0),
                                  fromcurrent=False, mode="immediate")]),
            dict(label="❚❚", method="animate",
                 args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")]),
        ])],
    )
    n_ot = int(row["overtime_periods"])
    fig.update_xaxes(range=[0, end + 0.8], tickvals=[0, 12, 24, 36, 48] + [50.5 + 5 * i for i in range(n_ot)],
                     ticktext=["Start", "Q2", "Half", "Q4", "End of Q4"]
                     + [("OT" if i == 0 else f"{i + 1}OT") for i in range(n_ot)])
    lim = max(10, float(m["margin"].abs().max()) + 4)
    show(fig, 430, yaxis=dict(title="Clippers ahead ↑ / behind ↓", range=[-lim, lim]))
    st.caption("Shaded: the biggest run each way. Press ▶ Replay to watch it unfold; hover a turnover for who, "
               "what and what it cost.")
    with st.expander("Inside the runs"):
        for run in (run_against, run_for):
            if run is None:
                continue
            side = f"{opp} run" if run.against else "Clippers run"
            scorers = ", ".join(f"{n} {v}" for n, v in run.opp_scorers) or "nobody"
            st.markdown(f"**{side} {run.label}** ({R.run_window(run)}). On the floor for LAC: "
                        f"{', '.join(run.unit) or '?'}. Clippers turnovers: {', '.join(run.turnovers) or 'none'}; "
                        f"missed shots: {run.misses}; {opp} offensive rebounds: {run.opp_orebs}. "
                        f"{opp} points: {scorers}.")

    # ---- what decided it, and what needed to happen
    if len(factors):
        won = row["final_margin"] > 0
        heading("What decided it" if won else "What needed to happen", "decided")
        st.markdown(f'<div class="takeaway">Compared with their average game this season '
                    f'({signed(factors.attrs["normal_margin"])} a game), here\'s where this one was better or worse.'
                    "</div>", unsafe_allow_html=True)
        fz = factors[factors["factor"] != "residual"]
        better = fz[fz["points"] >= 0.5].sort_values("points", ascending=False)
        worse = fz[fz["points"] <= -0.5].sort_values("points")
        top = float(fz["points"].abs().max() or 1)

        def ledger(rows: pd.DataFrame, color: str, title: str, empty: str) -> str:
            items = "".join(
                f'<div class="ledger-row"><div class="lname">{n}</div><div class="lbar"><span style="width:'
                f'{100 * abs(v) / top:.0f}%;background:{color}"></span></div>'
                f'<div class="lval" style="color:{color}">{signed(v)}</div></div>'
                for n, v in zip(rows["name"], rows["points"]))
            return (f'<div class="ledger"><div class="lhead" style="color:{color}">{title}</div>'
                    + (items or f'<div class="lempty">{empty}</div>') + "</div>")

        normal, final = factors.attrs["normal_margin"], factors.attrs["margin"]
        st.markdown(f'<div class="ledger-sum">A normal night: <b>{signed(normal)}</b> &nbsp;→&nbsp; this game: '
                    f'<b style="color:{GOOD if final > 0 else BAD}">{signed(final, 0)}</b></div>',
                    unsafe_allow_html=True)
        left_, right_ = st.columns(2, gap="large")
        left_.markdown(ledger(better, GOOD, "▲ Better than a normal night", "Nothing stood out."),
                       unsafe_allow_html=True)
        right_.markdown(ledger(worse, BAD, "▼ Worse than a normal night", "Nothing stood out."),
                        unsafe_allow_html=True)
        st.caption("Points each part of the game was worth compared with their average game this season. Better and "
                   "worse add up to the difference between the two margins (plus a little the bookkeeping can't place).")
        if not won and lvs:
            st.markdown("**The fixes, biggest first**")
            answer_cards([W.Verdict(lv.title, f"{lv.points:.0f} pts",
                                    _unit_rows(lv.units, names) if lv.units else "; ".join(lv.suggestions) or "—",
                                    "bad", "decided") for lv in lvs], link=False, big_size="1.5rem")

    # ---- who was out, then who played
    _who_was_out(gid, opp, opp_id_, lines, opp_lines)
    heading("Who played well", "players")
    if len(lines):
        st.markdown('<div class="takeaway">Every Clipper who played, best night first. The bar is his Game Score '
                    '(a one-number box-score summary); the tick marks 10, a good night.</div>', unsafe_allow_html=True)
        answer_cards([W.Verdict(
            f"{r_.player_name}{' · starter' if r_.starter else ''}", f"{int(r_.pts)} pts",
            f"{int(r_.reb)} reb · {int(r_.ast)} ast · {int(r_.tov)} TO · {int(r_.fgm)}/{int(r_.fga)} FG in "
            f"{r_.minutes:.0f} min · {signed(r_.plus_minus, 0)} on the floor. Game Score {r_.game_score:.1f}.",
            "good" if r_.game_score >= 10 else "bad" if r_.game_score < 3 else "info", "players",
            ("share", max(r_.game_score, 0) / 25, 10 / 25), D.headshot_url(r_.player_id))
            for r_ in lines.itertuples()], link=False, big_size="1.5rem")

    # ---- who guarded whom
    mu = R.matchups_for_game(data.matchups, gid, "LAC", opp_lines) if len(data.matchups) else pd.DataFrame()
    heading("Who guarded whom", "matchups")
    if mu.empty:
        st.info("Player tracking for this game isn't published yet (it usually appears a few hours after the game).")
    else:
        st.markdown(f'<div class="takeaway">{opp}\'s top scorers, and what they scored against each Clippers '
                    "defender.</div>", unsafe_allow_html=True)
        opp_id = int(g_all.loc[gid, "opponent_id"])
        tc = D.team_color(opp_id)
        cards = []
        for (scorer, total), grp in mu.groupby(["scorer", "scorer_pts"], sort=False):
            pid = opp_lines.loc[opp_lines["player_name"] == scorer, "player_id"]
            other = int(total - grp["pts"].sum())
            rows = "".join(
                f'<div class="sc-row"><img src="{face(d) or ""}" alt=""><div class="who">Guarded by '
                f'<b>{short(d)}</b><br><span style="opacity:.65">{int(m_)}/{int(a_)} shooting, '
                f'{pp:.0f} possessions</span></div><div class="pts" style="color:{BAD if p_ >= 10 else INK_MARK}">'
                f'{int(p_)}</div></div>'
                for d, p_, m_, a_, pp in zip(grp["defender"], grp["pts"], grp["fgm"], grp["fga"], grp["poss"]))
            cards.append(
                f'<div class="scard"><div class="sc-top" style="--tc:{tc};--td:{D.shade(tc)}">'
                f'<img class="logo" src="{D.logo_url(opp_id, dark=not D.is_light(tc))}" alt="">'
                + (f'<img class="face" src="{D.headshot_url(int(pid.iloc[0]))}" alt="">' if len(pid) else "")
                + f'<div class="sc-name">{scorer}</div></div><div class="sc-pts">{int(total)}<span>pts</span></div>'
                + rows
                + (f'<div class="sc-foot">The other {other}: other defenders, transition or the line.</div>'
                   if other > 0 else '<div class="sc-foot"></div>') + "</div>")
        st.markdown(f'<div class="scards" style="--cols:{min(len(cards), 3)}">{"".join(cards)}</div>',
                    unsafe_allow_html=True)
        st.caption("Points scored while each Clipper was his main defender (player tracking). Fast breaks and "
                   "scrambles with no clear defender aren't counted.")

    # ---- five-man units
    if len(game_units):
        heading("Which lineups worked", "units")
        ids_by_name = {v: k for k, v in names.items()}
        gu = game_units[game_units["seconds"] >= 120].sort_values("plus_minus", ascending=False)
        show_units = pd.concat([gu.head(3), gu.tail(3)]).drop_duplicates(subset=["team"])
        rows_html = []
        for u in show_units.itertuples():
            faces = "".join(f'<img src="{D.headshot_url(ids_by_name[n])}" alt="{n}" title="{n}">' for n in u.unit
                            if n in ids_by_name)
            color = GOOD if u.plus_minus > 0 else BAD if u.plus_minus < 0 else GRAY
            rows_html.append(
                f'<div class="lineup"><div class="faces">{faces}</div>'
                f'<div class="who">{", ".join(short(n) for n in u.unit)}</div>'
                f'<div class="min">{u.minutes:.0f} min</div>'
                f'<div class="pm" style="color:{color}">{signed(u.plus_minus, 0)}</div></div>')
        st.markdown('<div class="takeaway">The best and worst five-man units (2+ minutes together): points scored '
                    "minus allowed while they shared the floor.</div>" + "".join(rows_html), unsafe_allow_html=True)
        with st.expander("Every unit, as a chart"):
            gu2 = gu.sort_values("plus_minus")
            fig = go.Figure(go.Bar(
                y=[", ".join(short(n) for n in u_) for u_ in gu2["unit"]], x=gu2["plus_minus"],
                orientation="h", marker_color=[GOOD if v > 0 else BAD if v < 0 else MUTED_BAR for v in gu2["plus_minus"]],
                text=[f"{signed(v, 0)} in {mm:.0f} min" for v, mm in zip(gu2["plus_minus"], gu2["minutes"])],
                textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{x:+d}<extra></extra>"))
            lim = float(gu2["plus_minus"].abs().max() or 1) * 1.6
            fig.add_vline(x=0, line=dict(color=INK_MARK, width=1))
            fig.update_xaxes(range=[-lim, lim], title="Points scored minus allowed with that five on the floor")
            show(fig, 90 + 32 * len(gu2), showlegend=False)

    # ---- the details
    with st.expander("What changed after halftime in this game"):
        a = att.set_index("factor")
        fig = go.Figure(go.Bar(
            x=a["points"], y=[S.FACTOR_PLAIN[f][0] for f in a.index], orientation="h",
            marker_color=[GRAY if f == "residual" else GOOD if v >= 0 else BAD for f, v in a["points"].items()],
            customdata=[S.FACTOR_PLAIN[f][1] for f in a.index],
            hovertemplate="<b>%{y}</b>: %{x:+.1f} pts<br>%{customdata}<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.add_vline(x=0, line=dict(color=GRAY, width=1))
        show(fig, 300, xaxis_title=f"Points vs the first half (total {signed(a['margin_change'].iloc[0], 0)})")
    with st.expander("Box score"):
        cols = ["player_name", "starter", "minutes", "pts", "reb", "ast", "stl", "blk", "tov", "pf", "fgm", "fga",
                "fg3m", "fg3a", "ftm", "fta", "plus_minus", "game_score"]
        st.dataframe(with_photos(lines[cols].round(1)), hide_index=True, width="stretch", column_config=PHOTO_COL)
        if len(game_def):
            st.markdown("**Each Clippers defender's night (tracking)**")
            st.dataframe(with_photos(game_def[["def_player", "main_assignment", "poss", "pts", "fgm", "fga"]].round(1),
                                     "def_player"), hide_index=True, width="stretch", column_config=PHOTO_COL)
    with st.expander("Before vs after halftime: every stat (table)"):
        st.dataframe(D.game_half_table(data.game_halves, gid), hide_index=True, width="stretch",
                     column_config={"stat": st.column_config.TextColumn("", width="medium")})
    with st.expander("Every Clippers turnover in this game"):
        st.dataframe(with_photos(D.game_turnovers(data.turnovers, gid), "player"), hide_index=True, width="stretch",
                     column_config=PHOTO_COL)
    fill_toc(nav_)


TAPE = [  # (label, column, higher is better)
    ("Overall (net rating)", "net", True), ("Scoring (per 100)", "ortg", True), ("Defense (allowed per 100)", "drtg", False),
    ("Shooting accuracy", "efg", True), ("Opponents' shooting", "opp_efg", False),
    ("Ball security", "tov_pct", False), ("Forcing turnovers", "opp_tov_pct", True),
    ("Offensive rebounding", "oreb_pct", True), ("Defensive rebounding", "opp_oreb_pct", False),
    ("Getting to the line", "ft_rate", True),
]


def _faces(lean: list[tuple[str, int, str]]) -> str:
    """Small round headshots with name and the stat behind each pick."""
    return "".join(
        f'<div class="lean"><img src="{D.headshot_url(pid)}" alt=""><div><b>{short(name)}</b>'
        f'<br><span>{stat}</span></div></div>' for name, pid, stat in lean)


def _rating_line(who: str, t: pd.Series) -> str:
    """A net rating in words: "They're outscored by 5.7 points per 100 possessions (24th of 30): they score 110.2
    (20th) and allow 115.9 (25th)." """
    net = float(t["net"])
    lead = (f"{who} outscore teams by {net:.1f}" if net >= 0 else f"{who}'re outscored by {-net:.1f}")
    return (f"{lead} points per 100 possessions ({P._ord(t['net_rank'])} of 30): they score {t['ortg']:.1f} "
            f"({P._ord(t['ortg_rank'])}) and allow {t['drtg']:.1f} ({P._ord(t['drtg_rank'])}).")


def _out_row(name: str, player_id, status: str, reason: str, note: str, right: str = "") -> str:
    """One player on an injury report: face, name, status, the report's reason, and a line about him."""
    pic = D.headshot_url(int(player_id), small=True) if pd.notna(player_id) else face(name)
    return ('<div class="sc-row">' + (f'<img src="{pic}" alt="">' if pic else '<span class="o-blank"></span>')
            + f'<div class="who"><b>{name}</b> <span class="o-status o-{status.lower()}">{status}</span><br>'
            f'<span style="opacity:.65">{reason}</span><br><span class="o-why">{note}</span></div>'
            f'<div class="pts">{right}</div></div>')


def _out_card(team: str, logo: str, color: str, right: str, rows: list[str]) -> str:
    """A team's injury-report card: a team-colored header, then one row per player."""
    return (f'<div class="scard"><div class="o-top" style="--tc:{color};--td:{D.shade(color)}">'
            f'<img src="{logo}" alt=""><span>{team}</span><b>{right}</b></div>'
            + ("".join(rows) or '<div class="sc-foot">Nobody listed.</div>') + '<div class="sc-foot"></div></div>')


def _reason(text: str | None) -> str:
    return re.sub(r"^Injury/Illness\s*-\s*", "", text or "").strip() or "Not given"


def _who_was_out(gid: str, opp: str, opp_id: int, lines: pd.DataFrame, opp_lines: pd.DataFrame) -> None:
    """A played game: who was on the league's last injury report before tip-off, and whether each one played."""
    ctx = current()
    data, tid, season_now = ctx.data, ctx.settings.team_id, ctx.season_now
    gi = data.game_injuries
    rep = gi[(gi["game_id"] == gid) & gi["status"].isin(A.STATUS_WEIGHT)
             & ~gi["reason"].fillna("").str.startswith("G League")] if len(gi) else gi
    if gi.empty or not (gi["game_id"] == gid).any():
        return  # no report kept for this game (an older season, or one the league didn't post)
    heading("Who was out", "missing")
    st.markdown("<div class='takeaway'>From the NBA's last injury report before tip-off, and whether each player "
                "ended up playing.</div>", unsafe_allow_html=True)
    season_prev = ctx.season_prev
    allp = data.player_season.assign(k=lambda d: d["player_name"].map(A.name_key))
    now = allp[allp["season"] == season_now]
    prev = allp[allp["season"] == season_prev].sort_values("gp").drop_duplicates("k", keep="last").set_index("k")
    ids = dict(zip(allp["k"], allp["player_id"]))
    if len(data.roster):
        ids.update(zip(data.roster["player_name"].map(A.name_key), data.roster["player_id"]))

    def card(team_name: str, team: str, title: str, logo: str, color: str, box: pd.DataFrame) -> str:
        played = {A.name_key(n): r for n, r in zip(box["player_name"], box.itertuples())}
        avg = now[now["team_abbreviation"] == team].set_index("k")
        rows, sat = [], 0
        for r in rep[rep["team_name"] == team_name].itertuples():
            k = A.name_key(r.player_name)
            if k in played:
                b = played[k]
                note = f"Played anyway: {b.minutes:.0f} min, {int(b.pts)} pts."
            else:
                sat += 1
                note = "Didn't play."
            if k in avg.index:
                note += f" Averages {avg.loc[k, 'pts']:.1f} pts in {avg.loc[k, 'min']:.0f} min this season."
            elif k in prev.index:
                note += (f" Hasn't played this season; averaged {prev.loc[k, 'pts']:.1f} pts in "
                         f"{prev.loc[k, 'min']:.0f} min last season.")
            else:
                note += " Hasn't played this season."
            rows.append(_out_row(r.player_name, ids.get(k), r.status, _reason(r.reason), note))
        return _out_card(title, logo, color, f"{sat} sat out" if rows else "", rows)

    oc = D.team_color(opp_id)
    names_ = {int(t): n for t, n in zip(data.league_periods["team_id"], data.league_periods["team_name"])}
    st.markdown('<div class="scards" style="--cols:2">'
                + card(names_.get(tid, "LA Clippers"), "LAC", "Clippers", D.logo_url(tid, dark=True), "#1d428a", lines)
                + card(names_.get(opp_id, ""), opp, names_.get(opp_id, opp), D.logo_url(opp_id, dark=not D.is_light(oc)),
                       oc, opp_lines)
                + "</div>", unsafe_allow_html=True)


def _whos_out(pv, opp_id: int) -> None:
    """Both teams' players on the league's injury report for this game, with what each one's absence is worth."""
    ctx = current()
    tid = ctx.settings.team_id
    section("Who's out", "out",
            "From the NBA's official injury report. Each player's value is how much his team's scoring margin "
            "changes when he sits, counting only the part of him already in the team's numbers.")
    if not pv.injury_report:
        st.info("The league hasn't posted an injury report for this game yet (it comes out the day before). Until "
                "then the odds assume both teams at their usual strength.", icon=":material/schedule:")
        return

    def card(team: str, logo: str, color: str, out: pd.DataFrame) -> str:
        total = min(float(out["expected"].sum()), A.TEAM_CAP) if len(out) else 0.0
        rows = []
        for r in out.itertuples():
            reason = _reason(r.reason)
            note = A.explain(r)
            if r.expected >= 0.05:
                note += (f" Worth {r.worth:.1f} pts" + (f", counted at {A.STATUS_WEIGHT[r.status]:.0%} because he's "
                                                       f"{r.status.lower()}" if r.status != "Out" else "") + ".")
            rows.append(_out_row(r.player_name, r.player_id, r.status, reason, note,
                                 "−" + format(r.expected, ".1f") if r.expected >= 0.05 else ""))
        return _out_card(team, logo, color, "−" + format(total, ".1f") + " pts" if total >= 0.05 else "no effect",
                         rows)

    oc = D.team_color(opp_id)
    st.markdown('<div class="scards" style="--cols:2">'
                + card("Clippers", D.logo_url(tid, dark=True), "#1d428a", pv.team_out)
                + card(pv.opponent_name, D.logo_url(opp_id, dark=not D.is_light(oc)), oc, pv.opp_out) + "</div>",
                unsafe_allow_html=True)
    st.caption(f"Out counts fully, Doubtful {A.STATUS_WEIGHT['Doubtful']:.0%}, Questionable "
               f"{A.STATUS_WEIGHT['Questionable']:.0%}. Value: on/off (team margin per 48 minutes with him on the "
               f"floor minus off it, this season and last, shrunk toward zero), times his share of the minutes "
               f"already in the team rating; never negative, at most {A.PLAYER_CAP:.0f} points a player and "
               f"{A.TEAM_CAP:.0f} a team. Late scratches after the morning update aren't included.")


def _game_plan(game: pd.Series, pv, teams: pd.DataFrame, shooting: float | None) -> None:
    """An upcoming game: the odds, a checklist of keys that updates them, matchups, and the tale of the tape."""
    ctx = current()
    data = ctx.data
    focus_last = ctx.focus_last
    season_now = ctx.season_now
    settings = ctx.settings
    tid = settings.team_id
    tip = game["tipoff_utc"].tz_convert("America/Los_Angeles")
    opp_id = int(game["away_id"] if pv.home else game["home_id"])
    st.markdown(f'<div class="kicker">{tip:%a %b} {tip.day} · {tip:%I:%M %p}'.replace(" 0", " ") + " PT · "
                f'{pv.arena} · {"home" if pv.home else "away"}</div>'
                f'<div class="hero">Clippers {"vs" if pv.home else "at"} {pv.opponent_name}</div>',
                unsafe_allow_html=True)
    lac, opp = pv.lac, pv.opp
    players = GP.player_table(data.player_box, season_now, "LAC")
    misc = data.team_misc[data.team_misc["season"] == season_now] if len(data.team_misc) else pd.DataFrame(
        columns=["team_id", "opp_pts_paint"])
    keys = GP.game_plan(pv, teams, misc, players, shooting)

    # ---- the odds, live with the keys picked below
    odds = st.empty()
    h2h = P.head_to_head(data.games, season_now, pv.opponent)
    played = data.games[(data.games["season"] == season_now)].sort_values("game_date")
    w_, l_ = int((played["result"] == "W").sum()), int((played["result"] == "L").sum())
    last5 = played.tail(5)
    record = f" Record {w_}-{l_}" + (f", {int((last5['result'] == 'W').sum())}-{int((last5['result'] == 'L').sum())} "
                                    "in the last 5." if len(played) > 5 else ".")
    tiles = [
        W.Verdict("Clippers this season", signed(lac["net"]), _rating_line("They", lac) + record,
                  "bad" if lac["net"] < 0 else "good", "plan", ("rank", int(lac["net_rank"]), 30), D.logo_url(tid)),
        W.Verdict(f"{pv.opponent} this season", signed(opp["net"]), _rating_line("They", opp),
                  "bad" if opp["net"] > lac["net"] else "good", "plan", ("rank", int(opp["net_rank"]), 30),
                  D.logo_url(opp_id)),
    ]
    if len(h2h):
        wins = int((h2h["result"] == "W").sum())
        tiles.append(W.Verdict(
            "Against them this season", f"{wins}-{len(h2h) - wins}",
            "; ".join(f"{r.game_date:%b} {r.game_date.day} {'vs' if r.is_home else 'at'} {pv.opponent}: "
                      f"{'won' if r.result == 'W' else 'lost'} {int(r.team_pts)}-{int(r.opp_pts)}"
                      for r in h2h.itertuples()) + ".", "info", "plan"))

    _whos_out(pv, opp_id)

    section(f"How to beat the {pv.opponent_name.split(' ')[-1]}", "plan",
            "The keys to this game from both teams' season numbers. Switch them on and off: the odds above "
            "update.")
    chosen = []
    if keys:
        for j, k in enumerate(keys):
            with st.container(border=True, key=f"key_{k.kind}"):
                c1, c2, c3 = st.columns([1.15, 2.4, 1.45], vertical_alignment="center", gap="medium")
                on = c1.toggle(k.title, value=False, key=f"plan_{game['game_id']}_{k.kind}")
                c1.markdown(f'<div class="kval">+{k.points:.1f} pts a game<br><span>{k.chance:.0%} to win with '
                            f"this alone</span></div>", unsafe_allow_html=True)
                c2.markdown(f'<div class="kwhy">{k.why}</div>', unsafe_allow_html=True)
                c3.markdown(_faces(k.lean_on), unsafe_allow_html=True)
                if on:
                    chosen.append(k)
        st.caption("Keys overlap a little (a turnover avoided can also be a shot that misses), so several together "
                   "are a best case.")
    else:
        st.write("Nothing in either team's numbers points to a specific key: it's about playing their usual game.")
    pts = sum(k.points for k in chosen)
    chance = P.win_chance(pv.margin + pts)
    with odds.container():
        picture(G.odds_bar("LAC", pv.opponent, chance, pv.margin + pts, team_logo=D.logo_url(tid, dark=False),
                           opp_logo=D.logo_url(opp_id, dark=False)), max_width="900px")
        st.markdown(f'<div class="odds-note">Today <b>{pv.chance:.0%}</b>'
                    + (f' → with {len(chosen)} key{"s" if len(chosen) != 1 else ""} below <b>{chance:.0%}</b>'
                       if chosen else " · switch on keys below to see what they're worth") + "</div>"
                    + (f'<div class="odds-note">Injuries: {abs(pv.injury_edge):.1f} points in '
                       f'{"the Clippers&#39;" if pv.injury_edge > 0 else pv.opponent + "&#39;s"} favor, already '
                       f'included (both at full strength: {P.win_chance(pv.margin - pv.injury_edge):.0%}). '
                       '<a href="#out">Who&#39;s out</a></div>' if abs(pv.injury_edge) >= 0.05 else ""),
                    unsafe_allow_html=True)
        answer_cards(tiles, link=False)

    # ---- matchups
    # 30+ tracked possessions, so there are enough Clippers to give each scorer his own (the biggest scorer picks
    # first from the 100+ group; see who_to_watch)
    defenders = W.defenders(data.matchups, data.hustle, data.bio, season_now, "LAC",
                            min_poss=30) if len(data.matchups) else None
    watch = P.who_to_watch(data.player_season, data.bio, season_now, pv.opponent,
                           defenders.table if defenders is not None else None)
    longs = P.long_rotation(data.player_season, data.bio, season_now, pv.opponent)
    if len(watch):
        section("Matchups: who guards their scorers", "watch",
                f"{pv.opponent}'s top scorers this season, and a different Clipper for each: the best defender goes "
                "to the biggest scorer, each one close in size and allowing the fewest points per possession "
                "(player tracking).")
        tc = D.team_color(opp_id)
        cards = []
        for r in watch.itertuples():
            size = (f"{G._ft_in(r.height_in)}, {r.weight_lb:.0f} lb · " if pd.notna(r.height_in)
                    and pd.notna(r.weight_lb) else "")
            listed = pv.opp_out[pv.opp_out["player_name"].map(A.name_key) == A.name_key(r.player_name)]                 if len(pv.opp_out) else pv.opp_out
            flag = (f'<span class="o-status o-{listed.iloc[0]["status"].lower()}" style="margin-left:.4rem">'
                    f'{listed.iloc[0]["status"]} tonight</span>' if len(listed) else "")
            guard = ""
            if r.guard_with:
                vs = (f"allows {r.guard_pts100:.0f} pts per 100 possessions (team average: {defenders.team_pts100:.0f})"
                      if pd.notna(r.guard_pts100) and defenders is not None else "")
                guard = (f'<div class="sc-row"><img src="{face(r.guard_with) or ""}" alt=""><div class="who">'
                         f'Guard him with <b>{r.guard_with}</b><br><span style="opacity:.65">{vs}</span></div></div>')
            cards.append(
                f'<div class="scard"><div class="sc-top" style="--tc:{tc};--td:{D.shade(tc)}">'
                f'<img class="logo" src="{D.logo_url(opp_id, dark=not D.is_light(tc))}" alt="">'
                f'<img class="face" src="{D.headshot_url(int(r.player_id))}" alt="">'
                f'<div class="sc-name">{r.player_name}</div></div>'
                f'<div class="sc-pts">{r.pts:.1f}<span>ppg</span>{flag}</div>'
                f'<div class="sc-foot" style="padding-top:.1rem">{size}{r.reb:.1f} reb, {r.ast:.1f} ast in '
                f'{r.min:.0f} min</div>{guard}<div class="sc-foot"></div></div>')
        st.markdown(f'<div class="scards" style="--cols:{min(len(cards), 3)}">{"".join(cards)}</div>',
                    unsafe_allow_html=True)
        if len(longs) >= P.LONG_ROTATION:
            st.warning(f"{pv.opponent} plays {len(longs)} players between 6'6\" and 6'10\" in its top eight "
                       f"({', '.join(longs)}). {focus_last} turns it over about twice as often against defenders "
                       "that size: get him the ball on the move or off screens.", icon=":material/height:")
        elif longs:
            st.caption(f"{pv.opponent}'s 6'6\"-6'10\" rotation players: {', '.join(longs)}.")

    # ---- tale of the tape
    section("Tale of the tape", "tape", "League rank on each part of the game (1st = best). Further right is better.")
    fig = go.Figure()
    labels = [x[0] for x in TAPE]
    for name, row_, color in (("LAC", lac, H1C), (pv.opponent, opp, FOCUS)):
        fig.add_trace(go.Scatter(
            x=[row_[f"{c}_rank"] for _, c, _ in TAPE], y=labels, mode="markers+text", name=name,
            text=[P._ord(row_[f"{c}_rank"]) for _, c, _ in TAPE], textposition="top center",
            marker=dict(color=color, size=14, line=dict(color=BG, width=1.5)),
            hovertemplate="%{y}: %{text}<extra>" + name + "</extra>"))
    for lab, c, _ in TAPE:
        fig.add_shape(type="line", x0=lac[f"{c}_rank"], x1=opp[f"{c}_rank"], y0=lab, y1=lab,
                      line=dict(color=LIGHT, width=3), layer="below")
    fig.update_xaxes(range=[31, 0], tickvals=[30, 20, 10, 1], ticktext=["30th", "20th", "10th", "1st"],
                     title="League rank this season")
    fig.update_yaxes(autorange="reversed")
    show(fig, 90 + 40 * len(TAPE))

    with st.expander("How the odds and the game plan are worked out"):
        st.markdown(
            f"- **Team strength** is points scored minus allowed per 100 possessions this season, blended with last "
            f"season's while the sample is small: (games x this season + {P.PRIOR_GAMES} x last season) / "
            f"(games + {P.PRIOR_GAMES}).\n"
            f"- **Expected margin** = the difference in strength x expected possessions / 100, plus "
            f"{P.HOME_POINTS:.0f} points for the home team.\n"
            f"- **Win chance** treats the final margin as landing within about {P.MARGIN_SD:.1f} points of that, the "
            "usual spread of an NBA game.\n"
            "- **Keys** only appear when the numbers point to them; each rule (and how its points are counted) is "
            "written at the top of src/courtside/analysis/gameplan.py.\n"
            "- It doesn't know about injuries, rest or travel, and isn't betting advice. Models this simple pick "
            "roughly two in three NBA games correctly.")
        st.dataframe(teams[["team_name", "gp", "net", "prior_net", "blend_net", "pace"]].sort_values(
            "blend_net", ascending=False).round(1), hide_index=True, width="stretch")
