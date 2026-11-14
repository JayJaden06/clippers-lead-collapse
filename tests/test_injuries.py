"""The injury report: reading the league's PDF, and what each missing player is worth to the odds."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from courtside.analysis import availability as A
from courtside.ingest import injuries as I

FIXTURE = Path(__file__).parent / "fixtures" / "Injury-Report_2026-11-13_06_15PM.pdf"


def test_report_time_reads_both_file_name_styles():
    assert I.report_time("Injury-Report_2026-11-13_06_15PM.pdf") == datetime(2026, 11, 13, 18, 15)
    assert I.report_time("Injury-Report_2025-11-27_01PM.pdf") == datetime(2025, 11, 27, 13, 0)
    assert I.report_time("Injury-Report_2026-04-29_12_00AM.pdf") == datetime(2026, 4, 29, 0, 0)
    assert I.report_time("something-else.pdf") is None


def test_parse_reads_every_row_with_its_team_across_page_breaks():
    pytest.importorskip("pdfplumber")
    df = I.parse(FIXTURE.read_bytes(), FIXTURE.name)
    assert len(df) == 113
    assert "Page" not in set(df["team_name"])  # the page footer isn't a team
    okc = df[(df["matchup"] == "OKC@LAC") & (df["team_name"] == "Oklahoma City Thunder")]
    assert list(okc["player_name"]) == ["Chet Holmgren", "Ajay Mitchell", "Thomas Sorber", "Nikola Topic",
                                        "Cason Wallace", "Jalen Williams", "Jaylin Williams"]  # Mitchell on page 6
    row = okc.set_index("player_name").loc["Ajay Mitchell"]
    assert row["status"] == "Questionable" and row["reason"] == "Injury/Illness - Left Ankle Sprain"
    names = set(df["player_name"])
    assert {"Morez Johnson Jr.", "Sergio de Larrea", "Yanic Konan Niederhauser"} <= names  # "Last, First" flipped
    # a reason wrapped above and below the player's line is put back together
    assert df.set_index("player_name").loc["Jalen Suggs", "reason"] == \
        "Injury/Illness - Right Knee Contusion/Bone Bruise"


def test_same_rows_ignores_when_the_report_was_posted():
    a = pd.DataFrame({"report_time": [pd.Timestamp("2026-11-13 11:00")], "game_date": [pd.Timestamp("2026-11-13")],
                      "matchup": ["OKC@LAC"], "team_name": ["LA Clippers"], "player_name": ["X"], "status": ["Out"],
                      "reason": ["r"]})
    assert I.same_rows(a, a.assign(report_time=pd.Timestamp("2026-11-13 18:15")))
    assert not I.same_rows(a, a.assign(status="Questionable"))


def _league(season, margin_by_team):
    """Regulation totals for a 10-game season: one row per team (gp 10), the margin spread over the games."""
    return pd.DataFrame([{"season": season, "team_id": t, "team_name": n, "gp": 10, "pts": 1100 + m, "opp_pts": 1100,
                          "period": 1} for (t, n), m in margin_by_team.items()])


def test_values_count_only_what_is_already_in_the_team_rating():
    s = "2026-27"
    lp = _league(s, {(1, "Team A"): 50})  # +5 a game
    ps = pd.DataFrame([
        # Star: 36 min a game, +12 a game on the floor -> off the floor -7 over 120 min: on/off far above zero
        {"season": s, "player_id": 10, "player_name": "Star", "team_id": 1, "gp": 10, "min": 36.0, "plus_minus": 12.0},
        # Bench: barely plays, negative on/off
        {"season": s, "player_id": 11, "player_name": "Bench", "team_id": 1, "gp": 10, "min": 8.0, "plus_minus": -3.0},
    ])
    v = A.player_values(ps, lp, s, None).set_index("player_name")
    assert v.loc["Star", "onoff"] > 0 and 0 < v.loc["Star", "worth"] <= A.PLAYER_CAP
    assert v.loc["Bench", "worth"] == 0  # never makes his team better by sitting
    # baked in: 10 games of 75% of the minutes, blended with an empty prior of 10 games
    assert v.loc["Star", "baked"] == pytest.approx(0.75 * 10 / (10 + 10))

    inj = pd.DataFrame({"game_date": [pd.Timestamp("2026-11-13")] * 3, "matchup": "A@B", "team_name": "Team A",
                        "player_name": ["Star", "Bench", "Signed Yesterday"], "status": ["Questionable", "Out", "Out"],
                        "reason": ""})
    out = A.missing(inj, v.reset_index(), pd.Timestamp("2026-11-13"), "A@B", "Team A").set_index("player_name")
    assert out.loc["Star", "expected"] == pytest.approx(v.loc["Star", "worth"] * 0.5)
    assert out.loc["Signed Yesterday", "worth"] == 0  # never played for them: not in the rating, nothing to remove
    assert A.edge(out.iloc[0:0], out.reset_index()) == pytest.approx(out["expected"].sum())
    assert A.has_report(inj, pd.Timestamp("2026-11-13"), "A@B") and not A.has_report(inj, pd.Timestamp("2026-11-14"),
                                                                                       "A@B")


def test_team_total_is_capped():
    big = pd.DataFrame({"expected": [A.PLAYER_CAP] * 4})
    assert A.edge(big.iloc[0:0], big) == A.TEAM_CAP


def test_explain_says_why_a_player_counts_little():
    from types import SimpleNamespace as R
    new = A.explain(R(gp_now=0, gp_prev=0, team_games=12, onoff=0.0))
    assert "Hasn't played for them yet" in new
    hurt = A.explain(R(gp_now=3, gp_prev=33, team_games=12, onoff=0.3))
    assert "3 of their 12 games" in hurt and "Last season" in hurt and "about the same" in hurt
    star = A.explain(R(gp_now=12, gp_prev=70, team_games=12, onoff=7.0))
    assert star == "With him on the floor they're about 7.0 points per 48 minutes better."
    gone = A.explain(R(gp_now=0, gp_prev=60, team_games=12, onoff=-1.2))
    assert "Hasn't played this season" in gone and "hasn't been better" in gone


def test_reasons_wrapped_over_three_lines_or_a_page_break_stay_with_their_player():
    pytest.importorskip("pdfplumber")
    fx = Path(__file__).parent / "fixtures"
    a = I.parse((fx / "Injury-Report_2026-10-23_09_45PM.pdf").read_bytes()).set_index("player_name")["reason"]
    assert a["Cameron Carr"] == "Injury/Illness - Right Oblique Strain"  # "Tear" above him ran over from a page
    b = I.parse((fx / "Injury-Report_2026-11-08_08_45PM.pdf").read_bytes()).set_index("player_name")["reason"]
    assert b["Keshon Gilbert"] == "Injury/Illness - Left Knee Inflammation/Non-Surgical Procedure"


def test_pregame_reports_are_matched_to_their_own_game(tmp_path):
    pytest.importorskip("pdfplumber")
    folder = tmp_path / "injuries" / "pregame"
    folder.mkdir(parents=True)
    (folder / "0022600102.pdf").write_bytes(
        (Path(__file__).parent / "fixtures" / "Injury-Report_2026-10-23_09_45PM.pdf").read_bytes())
    (folder / "0022600102.name").write_text("Injury-Report_2026-10-23_09_45PM.pdf")
    pre = I.pregame_table(tmp_path)
    assert set(pre["game_id"]) == {"0022600102"} and pre["report_time"].notna().all()
    mine = pre[pre["matchup"] == "LAC@LAL"]
    assert set(mine["team_name"]) == {"LA Clippers", "Los Angeles Lakers"}
    assert len(pre) > len(mine)  # the report lists the whole night; the build keeps only this game's rows
