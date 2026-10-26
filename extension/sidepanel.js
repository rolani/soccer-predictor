const STORAGE_KEY = "sportybet-predictions";
const CHECKED_KEY = "sportybet-predictions-checked";
const PREDICTIONS_DIR_ID = "predictions-folder";
const DIR_HANDLE_KEY = "predictions-dir-handle";
const fileInput = document.getElementById("fileInput");
const loadFileBtn = document.getElementById("loadFileBtn");
const clearBtn = document.getElementById("clearBtn");

const idb = (() => {
  const DB = "sportybet-predictions";
  const STORE = "handles";
  function open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB, 1);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onupgradeneeded = (e) => {
        if (!e.target.result.objectStoreNames.contains(STORE)) {
          e.target.result.createObjectStore(STORE);
        }
      };
    });
  }
  return {
    async get(key) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readonly");
        const req = tx.objectStore(STORE).get(key);
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    },
    async set(key, value) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, "readwrite");
        tx.objectStore(STORE).put(value, key);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    },
  };
})();
const resetChecksBtn = document.getElementById("resetChecksBtn");
const emptyState = document.getElementById("empty");
const picksList = document.getElementById("picks");
const footer = document.getElementById("footer");
const countEl = document.getElementById("count");
const oddsEl = document.getElementById("odds");

function pickKey(p) {
  return `${p.match}|${p.tip}`;
}

function getCheckedSet() {
  try {
    const stored = localStorage.getItem(CHECKED_KEY);
    return stored ? new Set(JSON.parse(stored)) : new Set();
  } catch (_) {
    return new Set();
  }
}

function saveCheckedSet(checked) {
  try {
    localStorage.setItem(CHECKED_KEY, JSON.stringify([...checked]));
  } catch (_) {}
}

function parseOdds(s) {
  if (s == null || s === "") return 0;
  const cleaned = String(s).replace(/\s/g, "").replace(/,/g, ".");
  const n = parseFloat(cleaned);
  return isNaN(n) ? 0 : n;
}

function parseCSV(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const header = lines[0].toLowerCase();
  const hasLeague = header.includes("league");
  const rows = lines.slice(1).filter((r) => r.trim());
  const picks = [];
  for (const row of rows) {
    const parts = row.split(",").map((p) => p.trim());
    if (hasLeague && parts.length >= 4) {
      picks.push({
        league: parts[0],
        match: parts[1],
        tip: parts[2],
        odds: parseOdds(parts[3]),
      });
    } else if (parts.length >= 3) {
      picks.push({
        league: "",
        match: parts[0],
        tip: parts[1],
        odds: parseOdds(parts[2]),
      });
    }
  }
  return picks;
}

function parseTxt(text) {
  const lines = text.trim().split(/\r?\n/).filter((r) => r.trim());
  const picks = [];
  for (const line of lines) {
    const parts = line.split("|").map((p) => p.trim());
    if (parts.length >= 4) {
      picks.push({
        league: parts[0],
        match: parts[1],
        tip: parts[2],
        odds: parseOdds(parts[3]),
      });
    } else if (parts.length >= 3) {
      picks.push({
        league: "",
        match: parts[0],
        tip: parts[1],
        odds: parseOdds(parts[2]),
      });
    }
  }
  return picks;
}

function parseMd(text) {
  const lines = text.trim().split(/\r?\n/);
  const picks = [];
  let hasLeagueCol = false;
  for (const line of lines) {
    if (!line.trim().startsWith("|")) continue;
    const parts = line.split("|").map((p) => p.trim());
    if (parts.length < 5) continue;
    const first = (parts[1] || "").toLowerCase();
    if (first === "#" || /^[-:\s]+$/.test(first)) {
      hasLeagueCol = parts[2]?.toLowerCase() === "league";
      continue;
    }
    if (hasLeagueCol && parts.length >= 6) {
      picks.push({
        league: parts[2] || "",
        match: parts[3] || "",
        tip: parts[4] || "",
        odds: parseOdds(parts[5]),
      });
    } else if (parts.length >= 5) {
      picks.push({
        league: "",
        match: parts[2] || "",
        tip: parts[3] || "",
        odds: parseOdds(parts[4]),
      });
    }
  }
  return picks;
}

function parseFile(text, filename) {
  const ext = (filename || "").toLowerCase();
  if (ext.endsWith(".csv")) return parseCSV(text);
  if (ext.endsWith(".md")) return parseMd(text);
  return parseTxt(text);
}

function render(picks) {
  if (!picks || picks.length === 0) {
    emptyState.hidden = false;
    picksList.hidden = true;
    footer.hidden = true;
    if (resetChecksBtn) resetChecksBtn.hidden = true;
    return;
  }

  emptyState.hidden = true;
  picksList.hidden = false;
  footer.hidden = false;
  if (resetChecksBtn) resetChecksBtn.hidden = false;

  const checked = getCheckedSet();

  // Group by country then league; sort by country, then league name
  const COUNTRY_ORDER = [
    "England", "Spain", "Italy", "Germany", "France", "Portugal", "Netherlands",
    "Belgium", "Turkey", "Mexico", "USA", "Brazil", "Argentina", "Other",
  ];
  function countryFromLeague(league) {
    const s = (league || "").trim();
    if (!s) return "Other";
    const first = s.split(/\s+/)[0];
    return first || "Other";
  }
  function sortKey(league) {
    const country = countryFromLeague(league);
    const idx = COUNTRY_ORDER.indexOf(country);
    return [(idx >= 0 ? idx : 999), league];
  }
  const byLeague = new Map();
  for (const p of picks) {
    const league = (p.league || "").trim() || "Other";
    if (!byLeague.has(league)) byLeague.set(league, []);
    byLeague.get(league).push(p);
  }
  const sortedLeagues = [...byLeague.keys()].sort((a, b) => {
    const [ca, la] = sortKey(a);
    const [cb, lb] = sortKey(b);
    if (ca !== cb) return ca - cb;
    return la.localeCompare(lb);
  });

  let html = "";
  for (const league of sortedLeagues) {
    const leaguePicks = byLeague.get(league);
    html += `<li class="league-header">${escapeHtml(league)}</li>`;
    html += leaguePicks
      .map((p) => {
        const key = pickKey(p);
        const isChecked = checked.has(key);
        return `
    <li class="pick-item ${isChecked ? "pick-item--checked" : ""}" data-key="${escapeAttr(key)}">
      <label class="pick-check">
        <input type="checkbox" ${isChecked ? "checked" : ""} aria-label="Added to SportyBet">
        <span class="checkmark" title="Mark as added to SportyBet"></span>
      </label>
      <div class="pick-content">
        <span class="match">${escapeHtml(p.match)}</span>
        <span class="tip">${escapeHtml(p.tip)}</span>
        <span class="odds">${p.odds.toFixed(2)}</span>
      </div>
    </li>
  `;
      })
      .join("");
  }
  picksList.innerHTML = html;

  // Attach checkbox listeners
  picksList.querySelectorAll(".pick-check input").forEach((cb) => {
    cb.addEventListener("change", (e) => {
      const item = e.target.closest(".pick-item");
      const key = item?.dataset?.key;
      if (!key) return;
      const checked = getCheckedSet();
      if (e.target.checked) {
        checked.add(key);
        item.classList.add("pick-item--checked");
      } else {
        checked.delete(key);
        item.classList.remove("pick-item--checked");
      }
      saveCheckedSet(checked);
    });
  });

  countEl.textContent = `${picks.length} pick${picks.length === 1 ? "" : "s"}`;
  const totalOdds = picks.reduce((acc, p) => acc * (p.odds || 1), 1);
  oddsEl.textContent = `Combined: ${totalOdds.toFixed(1)}`;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function loadFromStorage() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const picks = JSON.parse(stored);
      render(picks);
      return;
    }
  } catch (_) {}
  render([]);
}

function saveToStorage(picks) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(picks));
  } catch (_) {}
}

function loadFileFromHandle(file) {
  const reader = new FileReader();
  reader.onload = (ev) => {
    const text = ev.target?.result || "";
    const picks = parseFile(text, file.name);
    render(picks);
    saveToStorage(picks);
  };
  reader.readAsText(file, "UTF-8");
}

async function openFileFromPredictionsFolder() {
  if (!("showOpenFilePicker" in window)) {
    fileInput.click();
    return;
  }
  try {
    let dirHandle = await idb.get(DIR_HANDLE_KEY);
    if (dirHandle) {
      const ok = await dirHandle.queryPermission?.({ mode: "read" });
      if (ok !== "granted") {
        const perm = await dirHandle.requestPermission?.({ mode: "read" });
        if (perm !== "granted") dirHandle = null;
      }
    }
    const [fileHandle] = await showOpenFilePicker({
      startIn: dirHandle || "documents",
      types: [
        { accept: { "text/csv": [".csv"] } },
        { accept: { "text/plain": [".txt"] } },
        { accept: { "text/markdown": [".md"] } },
      ],
      multiple: false,
    });
    const file = await fileHandle.getFile();
    loadFileFromHandle(file);
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error(err);
      fileInput.click();
    }
  }
}

async function selectPredictionsFolder() {
  if (!("showDirectoryPicker" in window)) {
    fileInput.click();
    return;
  }
  try {
    const dirHandle = await showDirectoryPicker({
      id: PREDICTIONS_DIR_ID,
      mode: "read",
      startIn: "documents",
    });
    await idb.set(DIR_HANDLE_KEY, dirHandle);
    openFileFromPredictionsFolder();
  } catch (err) {
    if (err.name !== "AbortError") {
      console.error(err);
    }
  }
}

fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  loadFileFromHandle(file);
  e.target.value = "";
});

loadFileBtn.addEventListener("click", () => {
  openFileFromPredictionsFolder();
});

const selectFolderBtn = document.getElementById("selectFolderBtn");
if (selectFolderBtn) {
  selectFolderBtn.addEventListener("click", () => {
    selectPredictionsFolder();
  });
}

clearBtn.addEventListener("click", () => {
  render([]);
  saveToStorage([]);
  saveCheckedSet(new Set());
});

if (resetChecksBtn) {
  resetChecksBtn.addEventListener("click", () => {
    saveCheckedSet(new Set());
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        const picks = JSON.parse(stored);
        render(picks);
      } catch (_) {}
    }
  });
}

loadFromStorage();
