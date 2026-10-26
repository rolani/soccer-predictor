# Security

This project is a local research app. It needs a **Cursor API key** at runtime and must never store that key in git.

## Reporting

Open a GitHub issue for non-sensitive bugs. For a leaked key or other secret, rotate it in the Cursor dashboard first, then contact the maintainer privately.

## What not to commit

- `.env` and any file containing `CURSOR_API_KEY=crsr_…`
- `FOOTBALL_DATA_API_KEY` or `PINNACLE_API_KEY` values
- `.runs/` and `.predictions/` (personal betting output)

`.env.example` is the public template (empty values only).
