"""Fetch predictions from research sources."""

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass
class Prediction:
    """Single prediction for accumulator."""

    match: str
    tip: str
    odds: float
    league: str
    source: str


def _fetch(url: str) -> BeautifulSoup | None:
    """Fetch and parse HTML."""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None


def fetch_soccersite(day: str) -> list[Prediction]:
    """Fetch from soccersite.com."""
    base = "https://www.soccersite.com"
    url = base if day == "today" else f"{base}/tomorrow-football-predictions"
    soup = _fetch(url)
    if not soup:
        return []

    predictions = []
    for link in soup.find_all("a", href=re.compile(r"predictions-.*-tips-and-stats")):
        text = link.get_text(strip=True)
        if not text or len(text) < 10:
            continue
        # Parse "TeamA vs TeamB" and tip/odds from link text
        parts = text.replace("\n", " ").split()
        if len(parts) < 4:
            continue
        # Look for odds pattern (e.g. 1.55, 2.10)
        odds_match = re.search(r"(\d+\.\d{2})", text)
        odds = float(odds_match.group(1)) if odds_match else 0.0
        if odds < 1.1 or odds > 10:
            continue
        # Tip: 1, X, 2, 1X, X2, 12, etc.
        tip_match = re.search(r"\b(1|X|2|1X|X2|12|O\d+\.\d+|U\d+\.\d+|GG|NG)\b", text, re.I)
        tip = tip_match.group(1).upper() if tip_match else "1X2"
        # Match: try to extract "TeamA vs TeamB" or similar
        match = " vs ".join(parts[:2]) if len(parts) >= 2 else text[:50]
        predictions.append(
            Prediction(
                match=match,
                tip=tip,
                odds=odds,
                league="",
                source="soccersite.com",
            )
        )
    return predictions[:50]


def fetch_footystats(day: str) -> list[Prediction]:
    """Fetch from footystats.org."""
    base = "https://footystats.org/predictions"
    url = base if day == "today" else f"{base}/tomorrow"
    soup = _fetch(url)
    if not soup:
        return []

    predictions = []
    for link in soup.find_all("a", href=re.compile(r"h2h-stats.*predictions")):
        text = link.get_text(strip=True)
        if not text or "vs" not in text.lower():
            continue
        # Parse "TeamA vs TeamB" and "Best : Market (odds)"
        odds_match = re.search(r"\((\d+\.\d{2})\)", text)
        odds = float(odds_match.group(1)) if odds_match else 0.0
        if odds < 1.05 or odds > 15:
            continue
        # Extract match
        vs_idx = text.lower().find(" vs ")
        if vs_idx == -1:
            continue
        match = text[: vs_idx + 10].split("Best")[0].strip() if "Best" in text else text[:60]
        # Extract tip/market
        tip_match = re.search(r"Best\s*:\s*([^(]+)\s*\([\d.]+\)", text)
        tip = tip_match.group(1).strip()[:30] if tip_match else "1X2"
        predictions.append(
            Prediction(
                match=match,
                tip=tip,
                odds=odds,
                league="",
                source="footystats.org",
            )
        )
    return predictions[:50]


def fetch_all(day: str) -> list[Prediction]:
    """Fetch from all sources and merge."""
    all_preds = []
    all_preds.extend(fetch_soccersite(day))
    all_preds.extend(fetch_footystats(day))
    return all_preds
