# Clippers Courtside

**An interactive data story and live season tracker for the LA Clippers, built in Python and Streamlit.**

**Live site: [clippers-courtside.streamlit.app](https://clippers-courtside.streamlit.app)**

Every game gets a report, every upcoming game gets odds and a game plan, and the whole season is checked against one question: *why do they keep losing leads after halftime?* It refreshes itself the morning after each game.

![The Games page: the intro, one live tile per page, and the game picker](docs/images/home.png)

## Why I built it

Watching the Clippers early in 2026-27, I kept seeing the same game: a good first half, a lead, then a third quarter where it all came apart. The popular explanations were Darius Garland's turnovers, fouling, or just bad luck. I wanted to know which of those the numbers actually support, so I pulled every play of every game from the NBA's stats site and tested each theory against the data, with the rules for "this is the cause" written down before I looked at the results.

Once that worked, I didn't want a one-off report that goes stale. So the project became a tracker: the same analysis reruns after every game, and every sentence on the site is generated from the numbers, so the verdicts can change as the season does.

## What's on the site

| Page | What it answers |
|---|---|
| **Games** | Every game this season. A played game opens its report: the scoreboard, a replay of the score margin with the biggest runs shaded, the best and worst Clippers, who was out (from the last injury report before tip-off, and whether each one played), which lineups won and lost, and what decided it compared with a normal night. An upcoming game opens its game plan: the win chance (adjusted for who's on the NBA's injury report), who's out and what each absence is worth, and the keys to that matchup, each with how many points it's worth. |
| **Blown leads** | The answer, ranked: which parts of the game cost them points after halftime, a shot map of where the shots stop falling, the popular theories checked one by one, what changed since last season, and "what if" switches to see how much each fix would be worth. |
| **Players** | Who loses the ball after halftime, player by player, with each player's games. |
| **Vs. the league** | Whether every team fades after halftime (most don't), with all 30 teams on one chart. |
| **What now?** | What the numbers point to: minutes, Garland's role, defense and size, and the players returning from injury, with what would change each piece of advice. |

<table>
<tr>
<td><img src="docs/images/blown-leads.png" alt="Blown leads: the headline, the first and second half on a court, and the answer cards"></td>
<td><img src="docs/images/game-report.png" alt="A game report: the strip of games and the scoreboard"></td>
</tr>
<tr>
<td><img src="docs/images/league.png" alt="Vs. the league: every team's logo placed by first-half level and second-half change"></td>
<td><img src="docs/images/what-now.png" alt="What now?: one card per recommendation, each with its number"></td>
</tr>
</table>

## What I found (as of Nov 8, 2026: 9 games)

- **It's their own shooting.** Shooting accuracy (eFG%) drops from 58% before halftime to 52% after, the second-largest drop in the league. That accounts for almost all of the second-half swing. Opponents actually shoot *worse* after the break.
- **Garland is part of it, not the main cause.** He makes 30% of the team's second-half turnovers on 20% of its plays, but his extra turnovers explain about 35% of the drop, short of the 40% I set in advance for calling something *the* cause. His turnovers jump against defenders 6'6" or taller, not against double teams.
- **Turnovers cost more, not happen more.** They turn it over about as often after halftime, but opponents score 1.5 points per turnover instead of 1.1.
- **Fouling and The Wall aren't it.** Fouling is a minor, long-standing factor, and opponents don't miss more free throws after halftime at Intuit Dome.
- **Nine games is a small sample.** The 90% range for the drop still includes zero, so these are leads to keep checking. The site says so, and the numbers above will move: the live site and [`reports/findings.md`](reports/findings.md) always have the current version.

## How it works

```
stats.nba.com ──► courtside pull ──► data/raw/  (every response cached once; gitignored)
                                        │
                  courtside build  ◄────┘   play-by-play → halves, margins, leads, turnovers,
                        │                    lineups, on/off, tracking, league context
                        ▼
                  data/processed/  (committed parquet tables, ~7 MB)
                        │
        courtside analyze + report ──► reports/analysis.json, findings.md, figures/
                        │
                        ▼
                  dashboard/app.py  (Streamlit; reads the processed tables only, no API calls)
```

- **Daily refresh.** A Windows scheduled task runs [`scripts/daily_refresh.ps1`](scripts/daily_refresh.ps1) when I sign in and at 8:30am: it pulls last night's game and the latest injury report, rebuilds everything, and pushes to `main` only if something new arrived. Streamlit Community Cloud redeploys from that push. It runs on my PC rather than in GitHub Actions because stats.nba.com blocks cloud servers.
- **Nothing typed by hand.** Verdicts, headlines, card text and even the list of injured players come from the data. Returning players are found from today's roster (missed a quarter of the games since joining, and played 10+ minutes a game in a recent season).
- **Tested.** 271 tests run on recorded API responses and the committed tables, including a headless run of every page; CI runs them on every push.

## Methodology

- **Blown lead:** led by 8+ points at some point in the first 30 minutes and lost. Thresholds are settings, with 5 and 12 run as sensitivity checks.
- **Where the second-half points went:** the change in margin from first half to second half is split exactly (it adds up by construction) into shooting accuracy, turnovers, offensive rebounds, free throws and pace, for the Clippers and their opponents. The usual "points off turnovers + free-throw points + …" double counts, so I don't use it. Details: [`analysis/decompose.py`](src/courtside/analysis/decompose.py).
- **Rules set before the results:** a factor *drives* the drop at 40%+ of it, *contributes* at 15–40%, and is *minor* below that. A league rank of 26–30 is "among the worst." Uncertainty comes from a bootstrap that resamples whole games.
- **Garland's share:** his second-half turnovers above his own baseline, using whichever baseline gives the theory the most credit (his first-half rate this season, or his second-half rate last season), each valued at what a lost possession costs.
- **Win chances:** net rating blended with last season's early on (`(games × this + 10 × last) / (games + 10)`), turned into an expected margin with 2 points of home court, and a normal spread of 12.5 points. Simple models like this pick about two in three NBA games. Details: [`analysis/preview.py`](src/courtside/analysis/preview.py).
- **Injuries:** the morning refresh reads the NBA's official injury report. Each listed player is worth his on/off (team margin per 48 minutes with him on the floor minus off it, this season and last, shrunk toward zero) times the share of him already in his team's blended rating, so a player who's been out all season, or never played for the team, changes nothing. Out counts fully, Doubtful 75%, Questionable 50%; never negative, capped at 4 points a player and 8 a team. Late scratches after the morning refresh aren't caught. Details: [`analysis/availability.py`](src/courtside/analysis/availability.py).
- **Colors** were checked with a palette validator for colorblind safety and 3:1 contrast on the light background: blue = better, orange = worse and the second half, gray = context.

## Run it yourself

Python 3.11+. With [uv](https://docs.astral.sh/uv/) (or plain `pip`):

```bash
uv venv --python 3.12
uv pip install -e ".[dashboard,dev,pipeline]"
pytest -q                 # 271 tests, offline

courtside dashboard       # open the site on the committed data, no API calls
```

To pull fresh data yourself:

```bash
courtside all             # pull → build → analyze → report
```

The first full pull makes several hundred API calls (about 10–15 minutes, throttled to stay polite to stats.nba.com); after that, only new games are fetched.

## Repo map

```
dashboard/app.py               the site's entry point: loads the data, sets up the menu, draws the page
src/courtside/
  cli.py                       courtside pull | build | analyze | report | all | dashboard
  nba_client.py                nba_api wrapper: browser headers, throttling, retries, disk cache
  ingest/                      one module per source: stats.nba.com (games, box scores, play-by-play, …)
                               and the NBA's injury report (a PDF from official.nba.com)
  transform/                   play-by-play → halves, margins, leads, turnovers, stints, on/off
  analysis/                    hypotheses, decomposition, game reports, odds and game plans
  viz/                         dashboard data, story text, What now? rules, SVG graphics
  web/                         the website: shared building blocks (ui.py), styles (style.css),
                               the per-visitor context, and views/ with one module per page
  names.py                     short player names that never mix two players up
data/processed/                the tables the site reads (committed)
reports/                       findings.md and figures, regenerated by `courtside report`
scripts/                       daily refresh and its scheduled-task installer, keep-awake ping
tests/                         unit tests on recorded fixtures, plus headless page runs
```

## What I'd do next

- **Injury status for returning players:** use the injury report's reasons so the returning-players list knows *why* someone sat.
- **Grade the odds:** track each game's predicted win chance against the result and show how well calibrated it is.
- **Lineup-level odds:** use who's actually available tonight instead of team-wide ratings.

## Data and credits

- Data from [stats.nba.com](https://www.nba.com/stats) through the open-source [nba_api](https://github.com/swar/nba_api) package. The data belongs to the NBA and is used here for personal, non-commercial analysis under the [NBA.com terms of use](https://content.nba.com/terms_of_service); requests are cached and throttled.
- Team logos and player headshots load from the NBA's image servers and belong to the NBA and its teams.
- A fan project, not affiliated with or endorsed by the NBA or the LA Clippers.
- Companion project: [clippers-home-court](https://clippers-home-court-h46at8hpdebg9gdcaunm87.streamlit.app), on whether Intuit Dome and The Wall changed the Clippers' home court.
