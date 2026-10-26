"""Export predictions for SportyBet and other bookmakers — CSV and plain-text."""

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExportedPick:
    """Single pick parsed from prediction file."""

    match: str
    tip: str
    odds: float
    league: str = ""


def parse_prediction_md(content: str) -> list[ExportedPick]:
    """
    Parse prediction markdown table into structured picks.
    Handles: | # | Match | Tip | Odds | or | # | League | Match | Tip | Odds |
    """
    picks = []
    lines = content.splitlines()
    has_league_col = None  # detect from header

    for line in lines:
        if not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        num = parts[1]
        if num == "#" or re.match(r"^[-:\s]+$", num):
            if num == "#" and len(parts) >= 6 and parts[2].lower() == "league":
                has_league_col = True
            elif num == "#" and parts[2].lower() == "match":
                has_league_col = False
            continue
        # Use header-detected format, or infer: 6+ parts and col2 != "match" => has league
        if has_league_col is True or (
            has_league_col is None and len(parts) >= 6 and parts[2].lower() != "match"
        ):
            league, match, tip, odds_str = parts[2], parts[3], parts[4], parts[5]
        else:
            league, match, tip, odds_str = "", parts[2], parts[3], parts[4]
        if match.lower() == "match":
            continue
        odds_match = re.search(r"[\d.]+", odds_str)
        if not odds_match:
            continue
        try:
            odds = float(odds_match.group(0))
        except ValueError:
            continue
        tip_clean = re.sub(r"\*\*", "", tip).strip()
        if not match or not tip_clean:
            continue
        picks.append(
            ExportedPick(
                match=match.strip(),
                tip=tip_clean,
                odds=odds,
                league=league.strip() if league else "",
            )
        )
    return picks


def to_csv(picks: list[ExportedPick]) -> str:
    """Format picks as CSV for Excel/spreadsheet."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["League", "Match", "Tip", "Odds"])
    for p in picks:
        writer.writerow([p.league, p.match, p.tip, f"{p.odds:.2f}"])
    return buf.getvalue()


def to_plain_text(picks: list[ExportedPick]) -> str:
    """Format picks as plain text — one line per pick, easy to copy."""
    lines = []
    for p in picks:
        if p.league:
            lines.append(f"{p.league} | {p.match} | {p.tip} | {p.odds:.2f}")
        else:
            lines.append(f"{p.match} | {p.tip} | {p.odds:.2f}")
    return "\n".join(lines)


def to_sportybet_search(picks: list[ExportedPick]) -> str:
    """
    Format match names only — for pasting into SportyBet search.
    One match per line so you can copy and search quickly.
    """
    lines = []
    seen = set()
    for p in picks:
        # Use match as search query (SportyBet often uses "Team A v Team B" or "Team A vs Team B")
        key = p.match.lower()
        if key not in seen:
            seen.add(key)
            lines.append(p.match)
    return "\n".join(lines)


def write_exports(
    picks: list[ExportedPick],
    output_dir: Path,
    base_name: str,
) -> dict[str, Path]:
    """Write SportyBet CSV, plain-text, and search files from structured picks."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}

    csv_path = output_dir / f"{base_name}_sportybet.csv"
    csv_path.write_text(to_csv(picks), encoding="utf-8")
    result["csv"] = csv_path

    txt_path = output_dir / f"{base_name}_sportybet.txt"
    txt_path.write_text(to_plain_text(picks), encoding="utf-8")
    result["txt"] = txt_path

    search_path = output_dir / f"{base_name}_sportybet_search.txt"
    search_path.write_text(to_sportybet_search(picks), encoding="utf-8")
    result["search"] = search_path

    return result


def write_exports_from_picks(picks, run_id: str, scope: str) -> dict[str, Path]:
    """Auto-export picks to .predictions/YYYY-MM-DD/ for the browser extension."""
    from datetime import datetime

    pred_root = Path(__file__).resolve().parents[1] / ".predictions"
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = pred_root / date_str
    base = run_id.replace("/", "-") + f"_{scope}"
    exported = [
        ExportedPick(match=p.match, tip=p.tip, odds=p.odds, league=getattr(p, "league", "") or "")
        for p in picks
        if getattr(p, "price_available", True) and p.odds is not None
    ]
    return write_exports(exported, out_dir, base)


def write_twitter_exports(
    picks,
    *,
    run_id: str,
    leagues_by_match: dict[str, str] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write gameweek Twitter full + thread text under .predictions/YYYY-MM-DD/."""
    from datetime import datetime

    from predictor.twitter import format_full, format_thread

    if output_dir is None:
        pred_root = Path(__file__).resolve().parents[1] / ".predictions"
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_dir = pred_root / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    base = run_id.replace("/", "-")

    full_path = output_dir / f"{base}_gameweek_twitter.txt"
    thread_path = output_dir / f"{base}_gameweek_twitter_thread.txt"
    full_path.write_text(
        format_full(picks, leagues_by_match=leagues_by_match),
        encoding="utf-8",
    )
    chunks = format_thread(picks, leagues_by_match=leagues_by_match)
    thread_path.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")
    return {"twitter_full": full_path, "twitter_thread": thread_path}


def export_file(
    input_path: Path,
    output_dir: Path | None = None,
    base_name: str | None = None,
) -> dict[str, Path]:
    """
    Read prediction markdown, export to CSV and plain-text.
    Returns dict of format_name -> output_path.
    """
    content = input_path.read_text(encoding="utf-8")
    picks = parse_prediction_md(content)
    if not picks:
        return {}

    out_dir = output_dir or input_path.parent
    base = base_name or input_path.stem.replace("_tomorrow", "").replace("_today", "")
    return write_exports(picks, out_dir, base)
