# SportyBet Predictions — Edge Side Panel

View your soccer predictions alongside SportyBet in a side panel.

## Install in Microsoft Edge

1. Open Edge and go to `edge://extensions/`
2. Turn on **Developer mode** (toggle in the left sidebar)
3. Click **Load unpacked**
4. Select the `extension` folder in this project (e.g. `c:\Users\laric\Documents\apps\predictor\extension`)
5. The extension will appear in your extensions list

## Use the side panel

1. Run `predict export` to generate `.csv` or `.txt` files in `.predictions/YYYY-MM-DD/`
2. Open SportyBet (or any site) in a tab
3. Click the **SportyBet Predictions** icon in the Edge toolbar (you may need to click the puzzle piece first and pin it)
4. In the side panel, click **Load file** — the first time, pick your `.predictions` folder; after that, the file picker opens directly in that folder
5. Your picks stay visible in the side panel while you place bets

## Features

- Load `.csv` or `.txt` prediction files — file picker opens in `.predictions` folder (after first-time folder selection)
- Parses both formats (Match,Tip,Odds and Match | Tip | Odds)
- **Checkbox** on each pick — tick as you add each to your SportyBet slip
- Check state persists (survives browser restart)
- **Reset checks** — clear all checkmarks
- Shows combined accumulator odds
- **Clear** button to reset everything
