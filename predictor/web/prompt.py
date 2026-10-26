"""Build agent prompts from run requests."""

from __future__ import annotations

from predictor.gameweek.board import format_gameweek_for_prompt
from predictor.gameweek.types import GameweekBoard
from predictor.live_fixtures import LiveFixtureBoard
from predictor.live_fixtures import format_board_for_prompt as format_live_board_for_prompt
from predictor.odds.board import PricedBoard, format_board_for_prompt
from predictor.web.market_mix import format_diversity_block, recent_market_mix
from predictor.web.schema import CreateRunRequest, Scope


def build_prompt(
    req: CreateRunRequest,
    run_id: str,
    live_board: LiveFixtureBoard | None = None,
    *,
    odds_board: PricedBoard | None = None,
    gameweek_board: GameweekBoard | None = None,
) -> str:
    scope_lines = {
        Scope.live: "Scope: **live** — only matches currently in play. Prefer no bet if nothing qualifies.",
        Scope.today: "Scope: **today** (Eastern). Remaining kickoffs only.",
        Scope.tomorrow: "Scope: **tomorrow** (Eastern). Full slate.",
        Scope.window: f"Scope: **window** — kickoffs within the next **{req.hours_window or 6} hours** (Eastern).",
        Scope.date: f"Scope: **date** — fixtures on **{req.target_date}** (Eastern).",
        Scope.gameweek: (
            "Scope: **gameweek** — remaining official matchdays for EPL, Bundesliga, "
            "La Liga, Serie A, and Ligue 1."
        ),
    }

    is_gameweek = req.scope == Scope.gameweek
    markets = (
        "Correct score"
        if is_gameweek
        else (", ".join(req.markets) if req.markets else "all markets")
    )
    pick_limit = (
        "Return one correct score for every remaining fixture (full slate)."
        if is_gameweek
        else (
            "Return all picks that pass the confidence and margin gates."
            if req.all_that_qualify or req.max_picks is None
            else f"Return at most **{req.max_picks}** picks (highest confidence first)."
        )
    )

    if is_gameweek:
        ticket_hint = (
            "Ticket mode: **content singles** — one correct score per remaining fixture; no acca."
        )
    else:
        ticket_hint = {
            "singles": "Ticket mode: **singles only** — no acca in suggested_tickets.",
            "acca": (
                f"Ticket mode: **acca** — build one acca with ~{req.acca_legs} legs, "
                f"combined odds {req.target_combined_odds_min}-{req.target_combined_odds_max}."
            ),
            "hybrid": (
                f"Ticket mode: **hybrid** — singles list plus one suggested acca "
                f"({req.acca_legs} legs, combined {req.target_combined_odds_min}-{req.target_combined_odds_max})."
            ),
        }[req.ticket_mode.value]

    league_filter = ""
    if req.league_include.strip():
        league_filter += f"\n- Include leagues matching: {req.league_include.strip()}"
    if req.league_exclude.strip():
        league_filter += f"\n- Exclude leagues matching: {req.league_exclude.strip()}"

    live_block = ""
    if req.scope == Scope.live:
        board = live_board
        if board is None:
            from predictor.live_fixtures import fetch_live_board

            board = fetch_live_board()
        live_block = (
            "\n\nRead `.cursor/skills/soccer-predictions/live-fixtures.md`.\n\n"
            + format_live_board_for_prompt(board)
        )

    workflow_live = """## Workflow (live)
1. Start from the live fixture board below (ESPN snapshot).
2. **Verify every candidate** on LiveScore, FlashScore, and Sofascore (minute, score, xG/shots/corners).
3. Use the board price when the fixture is listed. **If it is not, still publish** the pick with `price_available: false` and no `odds` — the UI shows research; the user finds a price elsewhere.
4. When a board price exists, include `odds` and apply the user's odds/margin gates.
5. Apply MASTER scenario penalties (sit-in knockout, pens script, 88' rule).
6. One pick per match; list weak/no-edge games in `skipped`.
7. Call **`submit_picks`** once — use `status: "live"`, `minute`, `score` on each pick."""

    workflow_default = f"""## Workflow
1. Verify kickoffs on ESPN, Guardian, LiveScore, or FlashScore (Eastern).
2. Research form (5–10), H2H (3–5), injuries, venue, market-specific stats.
3. Take the price from the priced market board below. Never invent one.
4. For each candidate: assign confidence 0–100, estimated_probability, short reasoning, 2–4 evidence bullets, risks.
5. List skipped fixtures in `skipped` with one-line why.
6. Call **`submit_picks`** exactly once with the final JSON payload (run_id `{run_id}`, scope `{req.scope.value}`)."""

    workflow_gameweek = f"""## Workflow (gameweek)
1. Start from the remaining-fixture board below (official matchdays).
2. **Verify every remaining fixture** on LiveScore, FlashScore, and Sofascore (kickoff, injuries, form).
3. Publish **exactly one correct score per remaining fixture**. `tip` is the scoreline (e.g. `2-1`); `market` is `Correct score`.
4. Set `price_available: false` and omit `odds` — no odds on this card.
5. Set each pick's `league` to that fixture's `round_label` (e.g. `EPL GW3`).
6. `estimated_probability` is the fair chance of that score (0–1). Evidence: 1–2 bullets with numbers.
7. Do **not** skip a match for weak evidence — publish and let `confidence` reflect it. List finished/mismatch/unconfirmed kickoffs in `skipped`.
8. Call **`submit_picks`** exactly once with the full slate (run_id `{run_id}`, scope `gameweek`)."""

    if req.scope == Scope.live:
        workflow = workflow_live
    elif is_gameweek:
        workflow = workflow_gameweek
    else:
        workflow = workflow_default

    priced_price_rules = """## Prices

Prices come from the priced market board. **Do not invent, estimate, or carry a
price over from a tip site or another book.** Set `odds` to the exact number on
the board for the market you choose.

If the market you want is not on the board, either choose a market that is, or
publish the pick with `price_available: false` and no `odds` — the research still
shows and the user sources the price themselves.

The server re-checks every price against the board and overwrites anything that
does not match, so a guessed number will simply be replaced."""
    priced_closer = (
        "**One pick per match.** Never submit Over 2.5 and team over 1.5 on the same fixture "
        "— pick the single market with the strongest evidence."
    )

    if is_gameweek:
        odds_thresholds = "- No odds on this card — set `price_available: false` and omit `odds`."
        conf_line = (
            f"Confidence 0–100 (floor does not drop lines; UI treats "
            f"`confidence` < 70 as low conf). Request min was {req.min_confidence}/100."
        )
        board_block = format_gameweek_for_prompt(gameweek_board) if gameweek_board else ""
        diversity_block = ""
        price_rules = """## Prices

No odds on this card. Set `price_available: false` and omit `odds`.
Do not invent, estimate, or copy a SportyBet price."""
        closer = "**One correct score per remaining fixture.** Diversity N/A — every pick is Correct score."
    else:
        if req.scope == Scope.live:
            odds_thresholds = (
                f"- Odds range: {req.min_odds} – {req.max_odds} (when SportyBet live price available)\n"
                f"- Margin buffer: {req.margin_buffer} above implied probability (1/odds) "
                "— skipped when `price_available: false`"
            )
        else:
            odds_thresholds = (
                f"- Odds range: {req.min_odds} – {req.max_odds}\n"
                f"- Margin buffer: {req.margin_buffer} above implied probability (1/odds)"
            )
        conf_line = f"Min confidence: {req.min_confidence}/100"
        board_block = format_board_for_prompt(odds_board) if odds_board else ""
        try:
            diversity_block = format_diversity_block(recent_market_mix())
        except Exception:  # never let history reading break a run
            diversity_block = format_diversity_block({})
        price_rules = priced_price_rules
        closer = priced_closer

    return f"""Run soccer prediction research for run_id `{run_id}`.

Follow `.cursor/skills/soccer-predictions/SKILL.md`, `markets.md`, and `run-schema.md`.
Read `.analysis/MASTER.md` for historical hit rates (priors, not bans).

{scope_lines.get(req.scope, scope_lines[Scope.today])}{live_block}

## User thresholds (apply when calling submit_picks)
- Markets: {markets}
- {conf_line}
- {pick_limit}
- {ticket_hint}{league_filter}
{odds_thresholds}

{workflow}

{price_rules}

{diversity_block}

{board_block}

{closer}

Do not write markdown files. Do not pad the board. Research quality is the gate.
"""
