"""Twitter export for gameweek correct-score cards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from predictor.exports import write_twitter_exports
from predictor.twitter import LOW_CONF_THRESHOLD, format_full, format_thread


def _pick(**kwargs) -> SimpleNamespace:
    defaults = dict(
        match="Arsenal vs Chelsea",
        tip="2-1",
        league="EPL GW3",
        confidence=80,
        estimated_probability=0.18,
        evidence=["Arsenal scored in 8/10 home games"],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _epl_pair() -> list[SimpleNamespace]:
    return [
        _pick(),
        _pick(
            match="Liverpool vs Man City",
            tip="1-1",
            confidence=65,
            estimated_probability=0.14,
            evidence=["Both sides drew 3 of last 5"],
        ),
    ]


class TestFormatThread:
    def test_low_conf_threshold_is_70(self):
        assert LOW_CONF_THRESHOLD == 70

    def test_compact_line_splits_match_on_vs_and_integer_percent(self):
        chunks = format_thread(_epl_pair())
        text = "\n".join(chunks)
        assert "Arsenal 2-1 Chelsea 18%" in text
        assert "Liverpool 1-1 Man City 14%" in text

    def test_low_conf_suffix_when_confidence_65(self):
        chunks = format_thread(_epl_pair())
        text = "\n".join(chunks)
        assert "Liverpool 1-1 Man City 14% · low conf" in text
        assert "Arsenal 2-1 Chelsea 18% · low conf" not in text

    def test_confidence_70_is_not_low_conf(self):
        chunks = format_thread([_pick(confidence=70)])
        text = "\n".join(chunks)
        assert " · low conf" not in text

    def test_league_header_on_first_chunk(self):
        chunks = format_thread(_epl_pair())
        assert chunks
        assert chunks[0].startswith("EPL GW3\n")

    def test_empty_league_uses_gameweek_header(self):
        chunks = format_thread([_pick(league="")])
        assert chunks[0].startswith("Gameweek\n")

    def test_thread_chunks_all_lte_280(self):
        picks = [
            _pick(
                match=f"Home{i:02d} vs Away{i:02d}",
                tip="1-0",
                estimated_probability=0.12,
                confidence=80 if i % 2 == 0 else 65,
                evidence=[f"Form note {i}"],
            )
            for i in range(20)
        ]
        chunks = format_thread(picks)
        assert chunks
        for chunk in chunks:
            assert len(chunk) <= 280

    def test_split_between_matches_only(self):
        picks = [
            _pick(
                match=f"Home{i:02d} vs Away{i:02d}",
                tip="1-0",
                estimated_probability=0.12,
                confidence=80,
                evidence=[f"Form note {i}"],
            )
            for i in range(20)
        ]
        chunks = format_thread(picks)
        compact = [f"Home{i:02d} 1-0 Away{i:02d} 12%" for i in range(20)]
        joined = "\n".join(chunks)
        for line in compact:
            assert line in joined
            assert not any(line in chunk and line not in chunk.splitlines() for chunk in chunks)
            assert any(line in chunk.splitlines() for chunk in chunks)

    def test_no_at_and_no_odds(self):
        chunks = format_thread(_epl_pair())
        text = "\n".join(chunks)
        assert "@" not in text
        assert "odds" not in text.lower()


class TestFormatFull:
    def test_format_full_includes_evidence_bullets(self):
        text = format_full(_epl_pair())
        assert "Arsenal 2-1 Chelsea 18%" in text
        assert "Liverpool 1-1 Man City 14% · low conf" in text
        assert "Arsenal scored in 8/10 home games" in text
        assert "Both sides drew 3 of last 5" in text
        assert text.startswith("EPL GW3\n")

    def test_format_full_no_at_and_no_odds(self):
        text = format_full(_epl_pair())
        assert "@" not in text
        assert "odds" not in text.lower()


class TestWriteTwitterExports:
    def test_write_twitter_exports_creates_both_files(self, tmp_path: Path):
        paths = write_twitter_exports(
            _epl_pair(),
            run_id="2026-08-26_12-00-00_gameweek",
            output_dir=tmp_path,
        )
        assert set(paths) == {"twitter_full", "twitter_thread"}
        assert paths["twitter_full"].exists()
        assert paths["twitter_thread"].exists()
        assert paths["twitter_full"].name.endswith("_gameweek_twitter.txt")
        assert paths["twitter_thread"].name.endswith("_gameweek_twitter_thread.txt")

        full = paths["twitter_full"].read_text(encoding="utf-8")
        thread = paths["twitter_thread"].read_text(encoding="utf-8")
        assert "Arsenal 2-1 Chelsea 18%" in full
        assert "Arsenal scored in 8/10 home games" in full
        assert "Arsenal 2-1 Chelsea 18%" in thread
        assert "@" not in full and "odds" not in full.lower()
        assert "@" not in thread and "odds" not in thread.lower()

    def test_thread_file_joins_chunks_with_separator(self, tmp_path: Path):
        picks = [
            _pick(
                match=f"Home{i:02d} vs Away{i:02d}",
                tip="1-0",
                estimated_probability=0.12,
                confidence=80,
                evidence=[f"Form note {i}"],
            )
            for i in range(20)
        ]
        chunks = format_thread(picks)
        assert len(chunks) >= 2
        paths = write_twitter_exports(
            picks,
            run_id="2026-08-26_threadsep_gameweek",
            output_dir=tmp_path,
        )
        body = paths["twitter_thread"].read_text(encoding="utf-8")
        assert "\n\n---\n\n".join(chunks) == body
