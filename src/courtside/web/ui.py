"""Building blocks shared by the pages: charts, pictures, cards, panels, headings and the On this page bar.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import re
from pathlib import Path

import streamlit as st

from courtside.viz import dashboard_data as D
from courtside.viz import graphics as G
from courtside.viz import story as S
from courtside.viz import whatnow as W
from courtside.web.context import current
from courtside.web.theme import BAD, GOOD, GRAY, MUTED_BAR, PLOTLY_CONFIG, TONE_COLOR, _minus


STYLE = (Path(__file__).parent / "style.css").read_text(encoding="utf-8")


def inject_style() -> None:
    """The site's stylesheet (courtside/web/style.css), once per run."""
    st.markdown(f"<style>\n{STYLE}\n</style>", unsafe_allow_html=True)


def show(fig: go.Figure, height: int, key: str | None = None, select: bool = False, **layout):
    """Render a plotly figure; with ``select=True`` clicks on points rerun the app and are returned."""
    settings_ = dict(height=height, margin=dict(l=8, r=8, t=36, b=8), hovermode="closest",
                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",  # the white panel shows
                     legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None, font=dict(size=13)),
                     hoverlabel=dict(align="left", font=dict(size=13)), font=dict(size=13),
                     barcornerradius=4, clickmode="event+select" if select else None)
    fig.update_layout(**(settings_ | layout))
    face_px = getattr(fig, "_face_px", None)
    if face_px:
        plot_h = height - 36 - 8 - face_px - 30  # plot area height, roughly, under the default margins
        for im in fig.layout.images:
            if im.yref == "paper":
                im.sizey = face_px / max(plot_h, 60)
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(zeroline=False)
    return st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG, key=key,
                           on_select="rerun" if select else "ignore", selection_mode="points")


def picture(svg: str, max_width: str | None = None) -> None:
    """Render one of the SVG graphics from courtside.viz.graphics."""
    style = f' style="max-width:{max_width};margin-left:auto;margin-right:auto"' if max_width else ""
    st.markdown(svg.replace('<div class="gfx">', f'<div class="gfx"{style}>', 1), unsafe_allow_html=True)


def clicked(event, field: str, memo: str):
    """The clicked point's ``field`` if this click is new since last run (so widgets can still be used)."""
    pts = event.selection.points if event and event.selection else []
    value = pts[0].get(field) if pts else None
    if value is None or st.session_state.get(memo) == value:
        return None
    st.session_state[memo] = value
    return value


def kicker() -> str:
    """The small line above every page title: team, season, and how fresh the data is."""
    ctx = current()
    data = ctx.data
    season_now = ctx.season_now
    last = pd.to_datetime(data.games.loc[data.games["season"] == season_now, "game_date"]).max()
    return f'<div class="kicker">LA Clippers · {season_now} season · through {last:%b} {last.day}</div>'


def page_top(title: str, subtitle: str, show_kicker: bool = True, band: bool = True) -> None:
    box = st.container(key="band_light_" + re.sub(r"\W+", "_", title.lower())) if band else st.container()
    with box:
        if show_kicker:
            st.markdown(kicker(), unsafe_allow_html=True)
        left, right = st.columns([4, 1], vertical_alignment="bottom")
        left.title(title)
        with right:
            glossary_button()
        st.markdown(f'<div class="page-sub">{subtitle}</div>', unsafe_allow_html=True)


def next_step(page, blurb: str) -> None:
    """The way on to the next page of the story, at the bottom of a page."""
    st.divider()
    left, right = st.columns([3, 1], vertical_alignment="center")
    left.markdown(f'<div class="takeaway">{blurb}</div>', unsafe_allow_html=True)
    right.page_link(page, label=f"Next: {page.title} →", width="stretch")


def track(before: float, after: float, lo: float, hi: float, after_color: str) -> str:
    """A thin before -> after track: gray dot at ``before``, colored dot at ``after``, a line between."""
    pos = lambda v: max(0.0, min(100.0, 100 * (v - lo) / (hi - lo) if hi > lo else 0.0))  # noqa: E731
    a, b = pos(before), pos(after)
    return (f'<div class="trk"><span class="ln" style="left:{min(a, b):.1f}%;width:{abs(b - a):.1f}%;'
            f'background:{after_color}"></span><span class="dot" style="left:{a:.1f}%;background:{MUTED_BAR}">'
            f'</span><span class="dot" style="left:{b:.1f}%;background:{after_color}"></span></div>')


def compare_panel(title: str, rows: list[tuple]) -> str:
    """A white side panel of before -> after rows.

    ``rows``: (label, before text, after text, before value, after value, higher is better, lo, hi, small print).
    """
    out = [f'<div class="cmp"><h4>{title}</h4>']
    for label, bt, at, bv, av, up, lo, hi, sub in rows:
        better = (av > bv) if up else (av < bv)
        color = GOOD if better and abs(av - bv) > 1e-9 else BAD if abs(av - bv) > 1e-9 else MUTED_BAR
        out.append(f'<div class="cmp-row"><div class="cmp-top"><span class="cmp-label">{label}</span>'
                   f'<span class="cmp-vals"><span class="b">{_minus(bt)}</span> → '
                   f'<span style="color:{color}">{_minus(at)}</span></span></div>'
                   + track(bv, av, lo, hi, color) + (f'<div class="cmp-sub">{sub}</div>' if sub else "") + "</div>")
    return "".join(out) + "</div>"


def face(name: str | None) -> str | None:
    """Small headshot URL for a player's full name (None if it isn't a player we know)."""
    ctx = current()
    PLAYER_IDS = ctx.player_ids
    pid = PLAYER_IDS.get(name) if name else None
    return D.headshot_url(pid, small=True) if pid is not None else None


def axis_faces(fig: go.Figure, sources: list[str | None], row_px: float, axis: str = "y") -> None:
    """A face next to each category label, in category order (the order the chart's rows were added).

    ``sources`` are image URLs (``face(name)``, or a team logo), one per category; None leaves that row bare.
    ``row_px`` is the height of one row (horizontal charts) or the face height (vertical ones).
    """
    h = row_px * (0.86 if axis == "y" else 1)
    for i, src in enumerate(sources):
        if not src:
            continue
        if axis == "y":
            fig.add_layout_image(source=src, xref="paper", yref="y", x=0, y=i, xanchor="right", yanchor="middle",
                                 sizex=0.5, sizey=0.86, sizing="contain", layer="above")
        else:
            fig.add_layout_image(source=src, xref="x", yref="paper", x=i, y=0, xanchor="center", yanchor="top",
                                 sizex=0.9, sizey=1, sizing="contain", layer="above")
    if axis == "y":
        fig.update_yaxes(ticklabelstandoff=int(h * 1.37) + 8)
    else:
        fig.update_xaxes(ticklabelstandoff=int(h) + 6)
        fig._face_px = h  # read by show() to size the face strip under the plot


def with_photos(df: pd.DataFrame, name_col: str = "player_name") -> pd.DataFrame:
    """The table with a photo column in front, for st.dataframe (use PHOTO_COL in its column_config)."""
    return df.assign(photo=[face(n) for n in df[name_col]])[["photo"] + list(df.columns)]


PHOTO_COL = {"photo": st.column_config.ImageColumn("", width="small")}


def glossary_button() -> None:
    with st.popover("What do these words mean?", icon=":material/menu_book:"):
        for term, text in S.GLOSSARY.items():
            st.markdown(f"**{term}**  \n{text}")


def answer_cards(cards: list[W.Verdict], link: bool = True, big_size: str | None = None) -> None:
    """Short-headline cards with one big number each; with ``link`` a click jumps to the card's section."""
    ctx = current()
    PLAYER_IDS = ctx.player_ids
    TEAM_LAST = ctx.team_last
    cards = [W.Verdict(c.title, _minus(c.big), _minus(c.small), c.tone, c.anchor, c.viz, c.image) for c in cards]

    def faces_html(c: W.Verdict) -> str:
        if c.image:
            return f'<img class="v-img" src="{c.image}" alt="" loading="lazy">'
        ids = D.names_in(f"{c.title} {c.big}", PLAYER_IDS, TEAM_LAST)[:5]
        return ('<div class="v-faces">' + "".join(f'<img src="{D.headshot_url(i, small=True)}" alt="" '
                                                 'loading="lazy">' for i in ids) + "</div>") if ids else ""

    big_style = f' style="font-size:{big_size}"' if big_size else ""
    html = "".join(
        (f'<a class="vcard" href="#{c.anchor}"' if link else '<div class="vcard"')
        + ">"
        + faces_html(c)
        + (f'<div class="v-title">{c.title}</div>' if c.viz or c.image else
           f'<div class="v-title"><span class="v-dot" style="background:{TONE_COLOR.get(c.tone, GRAY)}"></span>'
           f'{c.title}</div>')
        + f'<div class="v-big"{big_style}>{c.big}</div>'
        + (f'<div class="v-mini">{G.mini(c.viz, c.tone)}</div>' if c.viz else "")
        + f'<div class="v-small">{c.small}</div>' + ("</a>" if link else "</div>")
        for c in cards)
    n = len(cards)
    cols = n if n <= 4 else min(4, -(-n // 2))
    st.markdown(f'<div class="vcards" style="--cols:{cols}">{html}</div>', unsafe_allow_html=True)


TOC_LABELS = {
    "reasons": "Ranked reasons", "shots": "Where shots stop falling", "theories": "Theories", "changes": "Since last season",
    "whatif": "What if?", "stats": "Every stat", "minutes": "Minutes", "defense": "Defense & size",
    "returning": "Returning players", "garland": "Ball handling", "more": "More evidence", "runs": "How it played out", "decided": "What decided it",
    "missing": "Who was out", "players": "Who played well", "matchups": "Who guarded whom", "units": "Lineups", "who": "Losing the ball",
    "sloppier": "Sloppier?", "one": "One player", "plan": "Game plan", "out": "Who's out", "watch": "Their scorers",
    "tape": "Tale of the tape", "teams": "All 30 teams", "ranks": "Every rank",
}


def heading(title: str, anchor: str, toc: bool = True) -> None:
    """A section heading, listed in the page's On this page bar."""
    ctx = current()
    TOC = ctx.toc
    st.header(title, divider="gray", anchor=anchor)
    if toc:
        TOC.append((TOC_LABELS.get(anchor, title), anchor))


def toc_slot(name: str):
    """An empty slot near the top of a long page; ``fill_toc`` puts the section pills in it at the end."""
    return st.container(key=f"toc_{name}")


def fill_toc(slot) -> None:
    """Section pills for every heading drawn on this page (3 or more), the one on screen highlighted."""
    ctx = current()
    TOC = ctx.toc
    if len(TOC) < 3:
        return
    pills = "".join(f'<a href="#{a}" data-a="{a}">{label}</a>' for label, a in TOC)
    slot.html(
        f'<nav class="toc"><span class="lbl">On this page</span>{pills}</nav>'
        """<script>
        (function () {
          // Streamlit redraws elements, so look everything up live on each scroll rather than holding on to it.
          const mark = () => {
            const links = [...document.querySelectorAll('nav.toc a')];
            let current = null;
            for (const l of links) {
              const h = document.getElementById(l.dataset.a);
              if (h && h.getBoundingClientRect().top < 190) current = l.dataset.a;
            }
            links.forEach(l => l.classList.toggle('on', l.dataset.a === current));
          };
          if (!window.__tocBound) {
            let queued = false;
            document.addEventListener('scroll', () => {
              if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; mark(); }); }
            }, true);
            // pill clicks: land the heading just below the bar (Streamlit's own jump ignores scroll-margin)
            document.addEventListener('click', (e) => {
              const a = e.target.closest('nav.toc a');
              if (!a) return;
              const h = document.getElementById(a.dataset.a);
              const box = document.querySelector('[data-testid="stMain"]');
              if (!h || !box) return;
              e.preventDefault(); e.stopPropagation();
              box.scrollBy({top: h.getBoundingClientRect().top - 150, behavior: 'smooth'});
            }, true);
            window.__tocBound = true;
          }
          window.__tocMark = mark;
          setTimeout(mark, 300);
        })();
        </script>""", unsafe_allow_javascript=True)


def behind_notice() -> None:
    """Say so when a finished game isn't in the data yet (the morning refresh hasn't run)."""
    ctx = current()
    data = ctx.data
    settings = ctx.settings
    miss = D.games_missing(data.schedule, data.games, settings.team_id, pd.Timestamp.now(tz="UTC"))
    if len(miss):
        last = pd.to_datetime(data.games["game_date"]).max()
        st.markdown(f'<div class="behind"><b>Catching up:</b> {len(miss)} finished game'
                    f'{"s are" if len(miss) > 1 else " is"} not in yet. Everything here runs through '
                    f'{last:%b} {last.day}; the site refreshes each morning.</div>', unsafe_allow_html=True)


def section(title: str, anchor: str, takeaway: str = "", badge: tuple[str, str] | None = None,
            toc: bool = True) -> None:
    heading(title, anchor, toc)
    if badge:
        st.badge(badge[0], color=badge[1])
    if takeaway:
        st.markdown(f'<div class="takeaway">{takeaway}</div>', unsafe_allow_html=True)


def legend_only(fig: go.Figure, items: list[tuple[str, str, str]]) -> None:
    """Legend entries that don't depend on the color of a trace's first point."""
    for name, color, symbol in items:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=name,
                                 marker=dict(color=color, size=11, symbol=symbol)))
