const BASE_BG = [15, 20, 28];
const RULE_COLORS = {
  special: [116, 134, 216],
  hyper: [92, 147, 204],
  checker: [86, 114, 184],
  sum: [60, 145, 173],
  cross: [102, 120, 206],
  clone: [123, 97, 178],
};

const ICONS = {
  home: "⌂",
  back: "←",
  play: "▶",
  close: "✕",
  next: "≫",
  ruleMenu: "◇",
  rule: "⊞",
  hint: "✦",
  note: "✎",
  clearNotes: "⌧",
  erase: "⌫",
  easy: "○",
  normal: "△",
  hard: "□",
};

Object.assign(ICONS, {
  pause: "Ⅱ",
  resume: "▶",
  reset: "↺",
  nextPuzzle: ">",
});

const DISPLAY_NAMES = {
  standard: "Standard",
  anti_close_adjacent_3: "D",
  bishop_meet_digits: "N",
  checkerboard_odd: "O",
  clone_regions_set_equal: "M",
  cross_monotone: "X",
  hyper_3x3: "H",
  hyper3x3: "H",
  l_tromino_sum: "L",
  local_consecutive_exists: "T",
  special_monotone_3x3: "I",
};

const SESSION_STORAGE_KEY = "sudoku_variants_session_v1";
const RULE_BUTTON_ORDER = [
  "standard",
  "O",
  "H",
  "L",
  "T",
  "X",
  "N",
  "D",
  "I",
  "M",
];

const state = {
  catalog: null,
  currentRule: null,
  currentDifficulty: null,
  currentDataset: null,
  currentPuzzle: null,
  board: [],
  givens: [],
  notes: [],
  selectedIndex: 0,
  noteMode: false,
  hintCell: null,
  transientError: null,
  currentScreen: "rule",
  elapsedSeconds: 0,
  timerStartedAt: null,
  timerIntervalId: null,
  isPaused: false,
  autoFillTimerId: null,
  isAutoFilling: false,
};

const screens = {
  rule: document.getElementById("screen-rule"),
  difficulty: document.getElementById("screen-difficulty"),
  example: document.getElementById("screen-example"),
  game: document.getElementById("screen-game"),
};

const els = {
  ruleList: document.getElementById("rule-list"),
  difficultyList: document.getElementById("difficulty-list"),
  exampleTitle: document.getElementById("example-title"),
  exampleRuleName: document.getElementById("example-rule-name"),
  exampleDescription: document.getElementById("example-description"),
  exampleBoard: document.getElementById("example-board"),
  gameBoard: document.getElementById("game-board"),
  gameTitle: document.getElementById("game-title"),
  timerLine: document.getElementById("timer-line"),
  statusLine: document.getElementById("status-line"),
  keypad: document.getElementById("keypad"),
  noteToggle: document.getElementById("note-toggle"),
  ruleButton: document.getElementById("rule-button"),
  hintButton: document.getElementById("hint-button"),
  pauseButton: document.getElementById("pause-button"),
  resetButton: document.getElementById("reset-button"),
  nextButton: document.getElementById("next-button"),
  clearNotesButton: document.getElementById("clear-notes"),
  eraseCellButton: document.getElementById("erase-cell"),
  menuHome: document.getElementById("menu-home"),
  clearDialog: document.getElementById("clear-dialog"),
  ruleDialog: document.getElementById("rule-dialog"),
  pauseDialog: document.getElementById("pause-dialog"),
  dialogRuleChip: document.getElementById("dialog-rule-chip"),
  dialogRuleTitle: document.getElementById("dialog-rule-title"),
  dialogRuleCopy: document.getElementById("dialog-rule-copy"),
  resumeButton: document.getElementById("resume-button"),
};

function showScreen(key) {
  state.currentScreen = key;
  for (const [name, node] of Object.entries(screens)) {
    node.classList.toggle("is-hidden", name !== key);
  }
  if (key === "game" && state.currentPuzzle && !state.isPaused) {
    startTimerLoop();
  } else if (key !== "game") {
    stopTimerLoop();
  }
}

function parseGrid(text) {
  return Array.from(text, (ch) => Number(ch));
}

function cellKey(row, col) {
  return `${row},${col}`;
}

function coordsFromIndex(index) {
  return [Math.floor(index / 9), index % 9];
}

function indexFromCoords(row, col) {
  return row * 9 + col;
}

function blendRgb(base, overlay, alpha) {
  return [
    Math.round(base[0] * (1 - alpha) + overlay[0] * alpha),
    Math.round(base[1] * (1 - alpha) + overlay[1] * alpha),
    Math.round(base[2] * (1 - alpha) + overlay[2] * alpha),
  ];
}

function rgbToCss(rgb) {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function getCookie(name) {
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return "";
}

function setCookie(name, value) {
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; max-age=31536000; SameSite=Lax`;
}

function historyIdsForDataset(dataset) {
  const raw = getCookie(dataset.history_cookie_key);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === "string") : [];
  } catch {
    return [];
  }
}

function storeHistoryIds(dataset, ids) {
  setCookie(dataset.history_cookie_key, JSON.stringify(ids.slice(-500)));
}

function displayNameForRule(ruleMode, fallback = "") {
  if (DISPLAY_NAMES[ruleMode]) {
    return DISPLAY_NAMES[ruleMode];
  }
  return fallback || ruleMode || "Rule";
}

function vibrate(pattern) {
  if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
    navigator.vibrate(pattern);
  }
}

function wirePressHaptic(element, pattern = 10) {
  if (!element) {
    return;
  }
  let firedAt = 0;
  const fire = () => {
    const now = Date.now();
    if (now - firedAt < 80) {
      return;
    }
    firedAt = now;
    vibrate(pattern);
  };
  element.addEventListener("pointerdown", fire, { passive: true });
  element.addEventListener("touchstart", fire, { passive: true });
  element.addEventListener("mousedown", fire, { passive: true });
}

function displayNameForRuleEntry(ruleLike, fallback = "") {
  if (!ruleLike || typeof ruleLike !== "object") {
    return fallback || "Rule";
  }
  const keys = [ruleLike.rule_slug, ruleLike.rule_mode, ruleLike.type];
  for (const key of keys) {
    if (typeof key === "string" && DISPLAY_NAMES[key]) {
      return DISPLAY_NAMES[key];
    }
  }
  return fallback || ruleLike.short_name || ruleLike.rule_name || "Rule";
}

function formatElapsed(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function currentElapsedSeconds() {
  if (state.timerStartedAt == null) {
    return state.elapsedSeconds;
  }
  const runningSeconds = Math.max(0, Math.floor((Date.now() - state.timerStartedAt) / 1000));
  return state.elapsedSeconds + runningSeconds;
}

function updateTimerDisplay() {
  if (!els.timerLine) {
    return;
  }
  els.timerLine.textContent = formatElapsed(currentElapsedSeconds());
}

function stopTimerLoop() {
  if (state.timerIntervalId != null) {
    window.clearTimeout(state.timerIntervalId);
    state.timerIntervalId = null;
  }
}

function scheduleNextTimerTick() {
  if (!state.currentPuzzle || state.isPaused || state.currentScreen !== "game") {
    state.timerIntervalId = null;
    return;
  }
  updateTimerDisplay();
  const delay = 1000 - (Date.now() % 1000);
  state.timerIntervalId = window.setTimeout(scheduleNextTimerTick, delay);
}

function startTimerLoop() {
  stopTimerLoop();
  if (!state.currentPuzzle || state.isPaused) {
    updateTimerDisplay();
    return;
  }
  if (state.timerStartedAt == null) {
    state.timerStartedAt = Date.now();
  }
  scheduleNextTimerTick();
}

function pauseTimer() {
  state.elapsedSeconds = currentElapsedSeconds();
  state.timerStartedAt = null;
  stopTimerLoop();
  updateTimerDisplay();
}

function ruleDescriptionText() {
  if (state.currentRule?.rule_slug === "bishop_meet_digits") {
    return "盤面上の 1 は、斜め方向の移動をたどると全てひとつながりになります。どの 1 から始めても、別の 1 に移り続けて他の全ての 1 に到達できます。";
  }
  return state.currentDataset?.description_ja || "";
}

function decorateRule(rule) {
  return {
    ...rule,
    short_name: displayNameForRuleEntry(rule, rule.short_name),
  };
}

function persistSession() {
  try {
    const payload = {
      currentScreen: state.currentScreen,
      currentRuleSlug: state.currentRule?.rule_slug || null,
      currentDifficultyId: state.currentDifficulty?.id || null,
      currentPuzzleId: state.currentPuzzle?.id || null,
      board: state.board,
      givens: state.givens,
      notes: state.notes.map((set) => [...set]),
      selectedIndex: state.selectedIndex,
      noteMode: state.noteMode,
      hintCell: state.hintCell,
      elapsedSeconds: currentElapsedSeconds(),
      isPaused: state.isPaused,
    };
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Keep the app usable even when storage is unavailable.
  }
}

function loadSessionSnapshot() {
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function syncHistory(screen, { replace = false } = {}) {
  const payload = { screen };
  if (replace) {
    window.history.replaceState(payload, "", window.location.href);
  } else {
    window.history.pushState(payload, "", window.location.href);
  }
}

function availableRuleEntries() {
  const available = new Set(state.catalog.datasets.map((item) => item.rule_slug));
  return state.catalog.rules
    .filter((rule) => available.has(rule.rule_slug))
    .map(decorateRule);
}

function orderedRuleEntries() {
  const rules = availableRuleEntries();
  const standard = rules.find((rule) => rule.rule_slug === "standard");
  const variants = rules.filter((rule) => rule.rule_slug !== "standard");
  const buckets = new Map();
  for (const rule of variants) {
    const key = rule.short_name;
    const list = buckets.get(key) || [];
    list.push(rule);
    buckets.set(key, list);
  }

  const ordered = [];
  for (const token of RULE_BUTTON_ORDER) {
    if (token === "standard") {
      if (standard) {
        ordered.push({ ...standard, isStandard: true });
      }
      continue;
    }
    const key = token.startsWith("M") ? "M" : token;
    const list = buckets.get(key) || [];
    if (!list.length) {
      continue;
    }
    ordered.push(list.shift());
    buckets.set(key, list);
  }
  for (const leftover of buckets.values()) {
    for (const rule of leftover) {
      ordered.push(rule);
    }
  }
  return ordered;
}

function availableDifficultyEntriesForRule(ruleSlug) {
  const ids = new Set(
    state.catalog.datasets
      .filter((item) => item.rule_slug === ruleSlug)
      .map((item) => item.difficulty_id),
  );
  return state.catalog.difficulties.filter((difficulty) => ids.has(difficulty.id));
}

async function loadCatalog() {
  const response = await fetch("./data/catalog.json");
  if (!response.ok) {
    throw new Error("catalog.json を読み込めませんでした。先に web_dataset_builder.py を実行してください。");
  }
  state.catalog = await response.json();
}

async function loadDataset(difficultyId, ruleSlug) {
  const entry = state.catalog.datasets.find(
    (item) => item.difficulty_id === difficultyId && item.rule_slug === ruleSlug,
  );
  if (!entry) {
    throw new Error("選択した組み合わせのデータセットが見つかりません。");
  }
  const response = await fetch(`./data/${entry.path}`);
  if (!response.ok) {
    throw new Error(`データセットを読み込めませんでした: ${entry.path}`);
  }
  return response.json();
}

function visualSet(list) {
  return new Set((list || []).map(([row, col]) => cellKey(row, col)));
}

function isPeerCell(visualState, selectedRow, selectedCol, row, col) {
  if (row === selectedRow && col === selectedCol) {
    return false;
  }
  if (row === selectedRow || col === selectedCol) {
    return true;
  }
  if (visualState?.has_bishop_rule && Math.abs(row - selectedRow) === Math.abs(col - selectedCol)) {
    return true;
  }
  return false;
}

function cellBackground(entry, row, col, selected, hint, error, isExample = false) {
  const visual = entry.visual_state || {};
  let rgb = [...BASE_BG];
  const key = cellKey(row, col);

  if (visualSet(visual.special_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.special, 0.34);
  }
  if (visualSet(visual.hyper_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.hyper, 0.26);
  }
  if (visualSet(visual.checkerboard_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.checker, 0.22);
  }
  if (visualSet(visual.sum_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.sum, 0.32);
  }
  if (visualSet(visual.cross_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.cross, 0.28);
  }
  if (visualSet(visual.clone_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.clone, 0.28);
  }
  if (!isExample && selected && isPeerCell(visual, selected[0], selected[1], row, col)) {
    rgb = blendRgb(rgb, [88, 166, 255], 0.26);
  }
  if (hint && hint[0] === row && hint[1] === col) {
    rgb = blendRgb(rgb, [96, 196, 255], 0.46);
  }
  if (selected && selected[0] === row && selected[1] === col) {
    rgb = blendRgb(rgb, [88, 166, 255], 0.58);
  }
  if (error && error[0] === row && error[1] === col) {
    rgb = blendRgb(rgb, [226, 91, 91], 0.54);
  }
  return rgbToCss(rgb);
}

function sumLabelMap(visualState) {
  const map = new Map();
  for (const region of visualState.sum_regions || []) {
    const cells = region.cells || [];
    if (!cells.length) {
      continue;
    }
    const topLeft = [...cells].sort((a, b) => a[0] - b[0] || a[1] - b[1])[0];
    map.set(cellKey(topLeft[0], topLeft[1]), region.target_sum);
  }
  return map;
}

function renderBoard(container, entry, values, options = {}) {
  const {
    selected = null,
    notes = [],
    givens = [],
    hint = null,
    error = null,
    circleCells = [],
    interactive = false,
  } = options;
  container.innerHTML = "";
  const sumLabels = sumLabelMap(entry.visual_state || {});
  const circleSet = new Set(circleCells.map(([row, col]) => cellKey(row, col)));

  for (let index = 0; index < 81; index += 1) {
    const [row, col] = coordsFromIndex(index);
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cell";
    cell.dataset.row = String(row);
    cell.dataset.col = String(col);
    cell.style.background = cellBackground(entry, row, col, selected, hint, error, !interactive);
    if (!interactive) {
      cell.disabled = true;
    } else {
      cell.dataset.index = String(index);
      cell.addEventListener("mouseenter", () => {
        state.selectedIndex = index;
        renderGameBoard();
      });
      cell.addEventListener("focus", () => {
        state.selectedIndex = index;
        renderGameBoard();
      });
      cell.addEventListener("click", () => {
        state.selectedIndex = index;
        renderGameBoard();
      });
      cell.addEventListener("touchstart", () => {
        state.selectedIndex = index;
        renderGameBoard();
      }, { passive: true });
      cell.addEventListener("touchmove", (event) => {
        const nextIndex = selectionIndexFromTouchEvent(event);
        if (nextIndex == null || nextIndex === state.selectedIndex) {
          return;
        }
        event.preventDefault();
        state.selectedIndex = nextIndex;
        renderGameBoard();
      }, { passive: false });
    }

    const labelKey = cellKey(row, col);
    if (sumLabels.has(labelKey)) {
      const sum = document.createElement("div");
      sum.className = "sum-label";
      sum.textContent = String(sumLabels.get(labelKey));
      cell.appendChild(sum);
    }

    const value = values[index];
    if (value) {
      const span = document.createElement("span");
      span.className = "cell-value";
      span.textContent = String(value);
      if (givens[index]) {
        span.classList.add("is-given");
      } else {
        span.classList.add("is-user");
      }
      if (error && error[0] === row && error[1] === col) {
        span.classList.add("is-error");
      }
      cell.appendChild(span);
    } else if (interactive && notes[index]?.size) {
      const notesWrap = document.createElement("div");
      notesWrap.className = "cell-notes";
      for (let note = 1; note <= 9; note += 1) {
        const noteEl = document.createElement("div");
        noteEl.className = "cell-note";
        noteEl.textContent = notes[index].has(note) ? String(note) : "";
        notesWrap.appendChild(noteEl);
      }
      cell.appendChild(notesWrap);
    }

    if (circleSet.has(labelKey)) {
      const circle = document.createElement("div");
      circle.className = "cell-circle";
      cell.appendChild(circle);
    }
    container.appendChild(cell);
  }
}

function renderRuleScreen() {
  els.ruleList.innerHTML = "";
  const ordered = orderedRuleEntries();
  const standard = ordered.find((rule) => rule.isStandard);
  const variants = ordered.filter((rule) => !rule.isStandard);

  const before = document.createElement("div");
  before.className = "rule-spacer";
  const after = document.createElement("div");
  after.className = "rule-spacer";
  els.ruleList.appendChild(before);

  if (standard) {
    const button = document.createElement("button");
    button.className = "rule-card rule-card--standard";
    button.innerHTML = `<span class="rule-card__letter"></span>`;
    button.setAttribute("aria-label", "Standard");
    button.title = "Standard";
    wirePressHaptic(button, 10);
    button.addEventListener("click", () => {
      state.currentRule = standard;
      renderDifficultyScreen();
      showScreen("difficulty");
      syncHistory("difficulty");
      persistSession();
    });
    els.ruleList.appendChild(button);
  }

  els.ruleList.appendChild(after);

  for (const rule of variants) {
    const button = document.createElement("button");
    button.className = "rule-card";
    button.innerHTML = `<span class="rule-card__letter">${rule.short_name}</span>`;
    button.setAttribute("aria-label", rule.rule_name || rule.short_name);
    button.title = rule.rule_name || rule.short_name;
    wirePressHaptic(button, 10);
    button.addEventListener("click", () => {
      state.currentRule = rule;
      renderDifficultyScreen();
      showScreen("difficulty");
      syncHistory("difficulty");
      persistSession();
    });
    els.ruleList.appendChild(button);
  }
}

function renderDifficultyScreen() {
  els.difficultyList.innerHTML = "";
  for (const difficulty of availableDifficultyEntriesForRule(state.currentRule.rule_slug)) {
    const button = document.createElement("button");
    button.className = "difficulty-button";
    button.innerHTML = `<span class="difficulty-button__label">${difficulty.label}</span>`;
    button.setAttribute("aria-label", difficulty.label);
    button.title = difficulty.label;
    wirePressHaptic(button, 10);
    button.addEventListener("click", async () => {
      state.currentDifficulty = difficulty;
      state.currentDataset = await loadDataset(difficulty.id, state.currentRule.rule_slug);
      state.currentDataset.short_name = displayNameForRuleEntry(
        { rule_slug: state.currentRule.rule_slug, rule_mode: state.currentDataset.rule_mode },
        state.currentDataset.short_name,
      );
      state.currentDataset.puzzles = (state.currentDataset.puzzles || []).map((puzzle) => ({
        ...puzzle,
        short_name: displayNameForRuleEntry(
          {
            rule_slug: state.currentRule.rule_slug,
            rule_mode: puzzle.rule_mode || state.currentDataset.rule_mode,
          },
          puzzle.short_name,
        ),
      }));
      renderExampleScreen();
      showScreen("example");
      syncHistory("example");
      persistSession();
    });
    els.difficultyList.appendChild(button);
  }
}

function renderExampleScreen() {
  const dataset = state.currentDataset;
  els.exampleTitle.textContent = "Preview";
  els.exampleRuleName.textContent = dataset.short_name;
  els.exampleDescription.textContent = ruleDescriptionText();
  renderBoard(
    els.exampleBoard,
    dataset.example,
    parseGrid(dataset.example.solution_string),
    {
      circleCells: dataset.example.circle_cells || [],
      interactive: false,
    },
  );
}

function nextExpectedStep() {
  if (!state.currentPuzzle) {
    return null;
  }
  for (const step of state.currentPuzzle.guide_steps || []) {
    const index = indexFromCoords(step.row, step.col);
    if (state.board[index] !== step.value) {
      return step;
    }
  }
  return null;
}

function activeRules() {
  return state.currentPuzzle?.rules || state.currentDataset?.rules || [];
}

function hasRule(type) {
  return activeRules().some((rule) => rule?.type === type);
}

function valueAt(row, col, candidateRow = -1, candidateCol = -1, candidateValue = 0) {
  if (row === candidateRow && col === candidateCol) {
    return candidateValue;
  }
  return state.board[indexFromCoords(row, col)] || 0;
}

function normalizeRegionCells(region) {
  return (region || []).map(([row, col]) => {
    if (row >= 1 && row <= 9 && col >= 1 && col <= 9) {
      return [row - 1, col - 1];
    }
    return [row, col];
  });
}

function hyperRegions() {
  return [
    [1, 1], [1, 5], [5, 1], [5, 5],
  ].map(([topRow, leftCol]) => {
    const cells = [];
    for (let row = topRow; row < topRow + 3; row += 1) {
      for (let col = leftCol; col < leftCol + 3; col += 1) {
        cells.push([row, col]);
      }
    }
    return cells;
  });
}

function cellsInSameBlock(row, col) {
  const top = Math.floor(row / 3) * 3;
  const left = Math.floor(col / 3) * 3;
  const cells = [];
  for (let rr = top; rr < top + 3; rr += 1) {
    for (let cc = left; cc < left + 3; cc += 1) {
      cells.push([rr, cc]);
    }
  }
  return cells;
}

function candidateViolatesStandardRules(row, col, value) {
  for (let index = 0; index < 9; index += 1) {
    if (index !== col && state.board[indexFromCoords(row, index)] === value) {
      return true;
    }
    if (index !== row && state.board[indexFromCoords(index, col)] === value) {
      return true;
    }
  }
  for (const [rr, cc] of cellsInSameBlock(row, col)) {
    if ((rr !== row || cc !== col) && state.board[indexFromCoords(rr, cc)] === value) {
      return true;
    }
  }
  return false;
}

function candidateViolatesCheckerboard(row, col, value) {
  return hasRule("checkerboard_odd") && ((row + col) % 2 === 1) && (value % 2 === 0);
}

function candidateViolatesHyper(row, col, value) {
  if (!hasRule("hyper_3x3")) {
    return false;
  }
  return hyperRegions()
    .filter((cells) => cells.some(([rr, cc]) => rr === row && cc === col))
    .some((cells) =>
      cells.some(([rr, cc]) => (rr !== row || cc !== col) && state.board[indexFromCoords(rr, cc)] === value));
}

function candidateViolatesFarNeighbors(row, col, value) {
  if (!hasRule("anti_close_adjacent_3")) {
    return false;
  }
  const neighbors = [
    [row - 1, col],
    [row + 1, col],
    [row, col - 1],
    [row, col + 1],
  ].filter(([rr, cc]) => rr >= 0 && rr < 9 && cc >= 0 && cc < 9);
  return neighbors.some(([rr, cc]) => {
    const neighborValue = state.board[indexFromCoords(rr, cc)];
    return neighborValue !== 0 && Math.abs(neighborValue - value) < 3;
  });
}

function candidateViolatesTouchRule(row, col, value) {
  if (!hasRule("local_consecutive_exists")) {
    return false;
  }
  const neighbors = [
    [row - 1, col],
    [row + 1, col],
    [row, col - 1],
    [row, col + 1],
  ].filter(([rr, cc]) => rr >= 0 && rr < 9 && cc >= 0 && cc < 9);
  const filledNeighbors = neighbors
    .map(([rr, cc]) => state.board[indexFromCoords(rr, cc)])
    .filter((neighborValue) => neighborValue !== 0);
  return filledNeighbors.length === neighbors.length
    && !filledNeighbors.some((neighborValue) => Math.abs(neighborValue - value) === 1);
}

function candidateViolatesLTromino(row, col, value) {
  const rule = activeRules().find((entry) => entry?.type === "l_tromino_sum");
  if (!rule) {
    return false;
  }
  const regions = (rule.regions || []).map(normalizeRegionCells);
  return regions
    .filter((cells) => cells.some(([rr, cc]) => rr === row && cc === col))
    .some((cells) => {
      let sum = 0;
      let emptyCount = 0;
      for (const [rr, cc] of cells) {
        const cellValue = valueAt(rr, cc, row, col, value);
        if (cellValue === 0) {
          emptyCount += 1;
        }
        sum += cellValue;
      }
      if (sum > 13) {
        return true;
      }
      if (sum + emptyCount * 9 < 13) {
        return true;
      }
      if (sum + emptyCount > 13) {
        return true;
      }
      return false;
    });
}

function candidateViolatesCross(row, col, value) {
  const rule = activeRules().find((entry) => entry?.type === "cross_monotone");
  if (!rule) {
    return false;
  }
  const crosses = rule.crosses || [];
  const makeSequence = (centerRow, centerCol, deltaRow, deltaCol, length) => {
    const sequence = [[centerRow, centerCol]];
    for (let step = 1; step <= length; step += 1) {
      const rr = centerRow + deltaRow * step;
      const cc = centerCol + deltaCol * step;
      if (rr < 0 || rr >= 9 || cc < 0 || cc >= 9) {
        break;
      }
      sequence.push([rr, cc]);
    }
    return sequence;
  };
  for (const cross of crosses) {
    const center = Array.isArray(cross.center) ? cross.center : null;
    if (!center || center.length !== 2) {
      continue;
    }
    const centerRow = center[0] >= 1 ? center[0] - 1 : center[0];
    const centerCol = center[1] >= 1 ? center[1] - 1 : center[1];
    const sequences = [
      makeSequence(centerRow, centerCol, -1, 0, cross.up_len ?? 0),
      makeSequence(centerRow, centerCol, 1, 0, cross.down_len ?? 0),
      makeSequence(centerRow, centerCol, 0, -1, cross.left_len ?? 0),
      makeSequence(centerRow, centerCol, 0, 1, cross.right_len ?? 0),
    ];
    for (const sequence of sequences) {
      if (!sequence.some(([rr, cc]) => rr === row && cc === col)) {
        continue;
      }
      for (let index = 0; index < sequence.length - 1; index += 1) {
        const [r1, c1] = sequence[index];
        const [r2, c2] = sequence[index + 1];
        const v1 = valueAt(r1, c1, row, col, value);
        const v2 = valueAt(r2, c2, row, col, value);
        if (v1 !== 0 && v2 !== 0 && !(v1 < v2)) {
          return true;
        }
      }
    }
  }
  return false;
}

function candidateViolatesLocalRules(row, col, value) {
  return (
    candidateViolatesStandardRules(row, col, value)
    || candidateViolatesCheckerboard(row, col, value)
    || candidateViolatesHyper(row, col, value)
    || candidateViolatesFarNeighbors(row, col, value)
    || candidateViolatesTouchRule(row, col, value)
    || candidateViolatesLTromino(row, col, value)
    || candidateViolatesCross(row, col, value)
  );
}

function clearRelatedNotes(row, col, value) {
  for (let c = 0; c < 9; c += 1) {
    state.notes[indexFromCoords(row, c)].delete(value);
  }
  for (let r = 0; r < 9; r += 1) {
    state.notes[indexFromCoords(r, col)].delete(value);
  }
  const br = Math.floor(row / 3) * 3;
  const bc = Math.floor(col / 3) * 3;
  for (let rr = br; rr < br + 3; rr += 1) {
    for (let cc = bc; cc < bc + 3; cc += 1) {
      state.notes[indexFromCoords(rr, cc)].delete(value);
    }
  }
}

function stopAutoFill() {
  if (state.autoFillTimerId != null) {
    window.clearTimeout(state.autoFillTimerId);
    state.autoFillTimerId = null;
  }
  state.isAutoFilling = false;
}

function startAutoFill() {
  if (!state.currentPuzzle || state.isAutoFilling) {
    return;
  }
  const solution = parseGrid(state.currentPuzzle.solution_string);
  state.isAutoFilling = true;

  const step = () => {
    const nextIndex = state.board.findIndex((cell) => cell === 0);
    if (nextIndex < 0) {
      stopAutoFill();
      renderGameBoard();
      persistSession();
      pauseTimer();
      els.clearDialog.showModal();
      return;
    }
    state.board[nextIndex] = solution[nextIndex];
    state.notes[nextIndex].clear();
    renderGameBoard();
    persistSession();
    state.autoFillTimerId = window.setTimeout(step, 300);
  };

  renderGameBoard();
  state.autoFillTimerId = window.setTimeout(step, 300);
}

function gameplayRuleButtonLabel() {
  if (!state.currentPuzzle && !state.currentDataset && !state.currentRule) {
    return "";
  }
  const label = displayNameForRuleEntry(
    {
      rule_slug: state.currentRule?.rule_slug || state.currentDataset?.rule_slug,
      rule_mode: state.currentPuzzle?.rule_mode || state.currentDataset?.rule_mode,
      short_name: state.currentPuzzle?.short_name || state.currentDataset?.short_name,
    },
    state.currentPuzzle?.short_name || state.currentDataset?.short_name || "",
  );
  return label === "Standard" ? "S" : label;
}

function selectionIndexFromTouchEvent(event) {
  const touch = event.touches?.[0] || event.changedTouches?.[0];
  if (!touch) {
    return null;
  }
  const target = document.elementFromPoint(touch.clientX, touch.clientY);
  const cell = target?.closest?.(".cell[data-index]");
  if (!cell) {
    return null;
  }
  const nextIndex = Number(cell.dataset.index);
  return Number.isInteger(nextIndex) ? nextIndex : null;
}

function resetTransientError() {
  state.transientError = null;
}

function triggerInvalidEntry(row, col) {
  vibrate([24, 18, 44]);
  state.transientError = [row, col];
  renderGameBoard();
  window.setTimeout(() => {
    resetTransientError();
    renderGameBoard();
  }, 900);
}

function handleValueInput(value) {
  if (!state.currentPuzzle || state.isPaused || state.isAutoFilling) {
    return;
  }
  const index = state.selectedIndex;
  const [row, col] = coordsFromIndex(index);
  if (state.givens[index]) {
    return;
  }
  const correctValue = Number(state.currentPuzzle.solution_string[index]);
  if (state.board[index] === correctValue && correctValue !== 0) {
    return;
  }

  if (state.noteMode) {
    if (state.board[index] !== 0) {
      return;
    }
    if (candidateViolatesLocalRules(row, col, value)) {
      triggerInvalidEntry(row, col);
      return;
    }
    if (state.notes[index].has(value)) {
      state.notes[index].delete(value);
    } else {
      state.notes[index].add(value);
    }
    renderGameBoard();
    return;
  }

  if (value !== correctValue) {
    triggerInvalidEntry(row, col);
    return;
  }

  state.board[index] = value;
  vibrate(10);
  state.notes[index].clear();
  clearRelatedNotes(row, col, value);
  state.hintCell = null;
  const remainingEmpty = state.board.filter((cell) => cell === 0).length;
  if (remainingEmpty === 9) {
    startAutoFill();
    persistSession();
    return;
  }
  renderGameBoard();
  persistSession();
  if (state.board.every((cell) => cell !== 0)) {
    pauseTimer();
    els.clearDialog.showModal();
  }
}

function eraseCell() {
  if (state.isPaused || state.isAutoFilling) {
    return;
  }
  const index = state.selectedIndex;
  if (state.givens[index]) {
    return;
  }
  state.board[index] = 0;
  state.hintCell = null;
  renderGameBoard();
  persistSession();
}

function clearNotesAtSelection() {
  if (state.isPaused || state.isAutoFilling) {
    return;
  }
  state.notes[state.selectedIndex].clear();
  renderGameBoard();
  persistSession();
}

function renderNumberButtons() {
  els.keypad.innerHTML = "";
  const counts = Array.from({ length: 10 }, () => 0);
  for (const value of state.board) {
    if (value >= 1 && value <= 9) {
      counts[value] += 1;
    }
  }
  for (let value = 1; value <= 9; value += 1) {
    const remaining = Math.max(0, 9 - counts[value]);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "keypad-button";
    button.innerHTML = remaining > 0 ? `${value}<span>${remaining}</span>` : "&nbsp;";
    button.disabled = remaining <= 0;
    wirePressHaptic(button, 10);
    button.addEventListener("click", () => handleValueInput(value));
    els.keypad.appendChild(button);
  }
}

function renderGameBoard() {
  const selected = coordsFromIndex(state.selectedIndex);
  renderBoard(
    els.gameBoard,
    state.currentPuzzle,
    state.board,
    {
      selected,
      notes: state.notes,
      givens: state.givens,
      hint: state.hintCell,
      error: state.transientError,
      interactive: true,
    },
  );
  els.gameBoard.classList.toggle("board--paused", state.isPaused);
  els.ruleButton.textContent = gameplayRuleButtonLabel();
  els.statusLine.textContent = `${state.currentDifficulty.label} / ${state.currentPuzzle.short_name}`;
  els.noteToggle.classList.toggle("is-active", state.noteMode);
  els.pauseButton.classList.toggle("is-active", state.isPaused);
  els.resetButton.disabled = state.isAutoFilling;
  els.nextButton.disabled = state.isAutoFilling;
  els.hintButton.disabled = state.isAutoFilling;
  els.ruleButton.disabled = state.isAutoFilling;
  els.noteToggle.disabled = state.isAutoFilling;
  els.clearNotesButton.disabled = state.isAutoFilling;
  els.eraseCellButton.disabled = state.isAutoFilling;
  updateTimerDisplay();
  renderNumberButtons();
}

function preparePuzzle(puzzle) {
  stopAutoFill();
  state.currentPuzzle = puzzle;
  state.board = parseGrid(puzzle.puzzle_string);
  state.givens = state.board.map((value) => value !== 0);
  state.notes = Array.from({ length: 81 }, () => new Set());
  state.selectedIndex = Math.max(0, state.board.findIndex((value) => value === 0));
  state.noteMode = false;
  state.hintCell = null;
  state.transientError = null;
  state.elapsedSeconds = 0;
  state.timerStartedAt = Date.now();
  state.isPaused = false;
  els.gameTitle.textContent = state.currentDifficulty.label;
  renderGameBoard();
  startTimerLoop();
  persistSession();
}

function chooseRandomPuzzle(dataset) {
  const seen = historyIdsForDataset(dataset);
  const unseen = dataset.puzzles.filter((puzzle) => !seen.includes(puzzle.id));
  const pool = unseen.length ? unseen : dataset.puzzles;
  if (!unseen.length) {
    storeHistoryIds(dataset, []);
  }
  const pick = pool[Math.floor(Math.random() * pool.length)];
  const nextHistory = unseen.length ? [...seen, pick.id] : [pick.id];
  storeHistoryIds(dataset, nextHistory);
  return pick;
}

function startRandomPuzzle() {
  const puzzle = chooseRandomPuzzle(state.currentDataset);
  preparePuzzle(puzzle);
  showScreen("game");
  syncHistory("game");
  persistSession();
}

function resetCurrentPuzzle() {
  if (!state.currentPuzzle) {
    return;
  }
  if (els.pauseDialog.open) {
    els.pauseDialog.close();
  }
  preparePuzzle(state.currentPuzzle);
  showScreen("game");
  syncHistory("game");
  persistSession();
}

function openRuleDialog() {
  if (!state.currentDataset) {
    return;
  }
  els.dialogRuleChip.textContent = displayNameForRule(
    state.currentRule?.rule_slug || state.currentDataset.rule_mode || state.currentRule?.rule_mode,
    state.currentDataset.short_name,
  );
  els.dialogRuleTitle.textContent = "Rule";
  els.dialogRuleCopy.textContent = ruleDescriptionText();
  els.ruleDialog.showModal();
}

function pauseGame() {
  if (!state.currentPuzzle || state.isPaused || state.isAutoFilling) {
    return;
  }
  state.isPaused = true;
  pauseTimer();
  renderGameBoard();
  persistSession();
  els.pauseDialog.showModal();
}

function resumeGame() {
  if (!state.currentPuzzle) {
    return;
  }
  state.isPaused = false;
  if (els.pauseDialog.open) {
    els.pauseDialog.close();
  }
  startTimerLoop();
  renderGameBoard();
  persistSession();
}

function attachIcons() {
  document.getElementById("back-to-rule").textContent = ICONS.back;
  document.getElementById("back-to-difficulty").textContent = ICONS.back;
  document.getElementById("start-puzzle").textContent = ICONS.play;
  document.getElementById("clear-next").textContent = "Next";
  document.getElementById("clear-rule").textContent = "Rules";
  document.getElementById("clear-home").textContent = "Home";
  els.hintButton.textContent = ICONS.hint;
  els.pauseButton.textContent = ICONS.pause;
  els.resetButton.textContent = ICONS.reset;
  els.nextButton.textContent = ICONS.nextPuzzle;
  els.resumeButton.textContent = ICONS.resume;
  els.noteToggle.textContent = ICONS.note;
  els.clearNotesButton.textContent = ICONS.clearNotes;
  els.eraseCellButton.textContent = ICONS.erase;
}

function attachGlobalEvents() {
  document.getElementById("back-to-rule").addEventListener("click", () => {
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });
  document.getElementById("back-to-difficulty").addEventListener("click", () => {
    showScreen("difficulty");
    syncHistory("difficulty");
    persistSession();
  });
  wirePressHaptic(document.getElementById("back-to-rule"), 10);
  wirePressHaptic(document.getElementById("back-to-difficulty"), 10);
  wirePressHaptic(document.getElementById("start-puzzle"), 10);
  wirePressHaptic(els.menuHome, 10);
  wirePressHaptic(els.hintButton, 10);
  wirePressHaptic(els.pauseButton, 10);
  wirePressHaptic(els.resetButton, 10);
  wirePressHaptic(els.nextButton, 10);
  wirePressHaptic(els.ruleButton, 10);
  wirePressHaptic(els.noteToggle, 10);
  wirePressHaptic(els.clearNotesButton, 10);
  wirePressHaptic(els.eraseCellButton, 10);
  wirePressHaptic(document.getElementById("clear-next"), 10);
  wirePressHaptic(document.getElementById("clear-rule"), 10);
  wirePressHaptic(document.getElementById("clear-home"), 10);
  wirePressHaptic(els.resumeButton, 10);

  document.getElementById("start-puzzle").addEventListener("click", () => {
    startRandomPuzzle();
  });
  els.menuHome.addEventListener("click", () => {
    stopAutoFill();
    pauseTimer();
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });
  els.hintButton.addEventListener("click", () => {
    if (state.isPaused || state.isAutoFilling) {
      return;
    }
    const step = nextExpectedStep();
    if (!step) {
      return;
    }
    state.hintCell = [step.row, step.col];
    renderGameBoard();
    persistSession();
  });
  els.ruleButton.addEventListener("click", () => {
    if (state.isPaused || state.isAutoFilling) {
      return;
    }
    openRuleDialog();
  });
  els.pauseButton.addEventListener("click", () => {
    pauseGame();
  });
  els.resetButton.addEventListener("click", () => {
    if (state.isAutoFilling) {
      return;
    }
    resetCurrentPuzzle();
  });
  els.nextButton.addEventListener("click", () => {
    if (state.isAutoFilling) {
      return;
    }
    if (els.pauseDialog.open) {
      els.pauseDialog.close();
    }
    startRandomPuzzle();
  });
  els.resumeButton.addEventListener("click", () => {
    resumeGame();
  });
  els.pauseDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
  });
  els.ruleDialog.addEventListener("click", (event) => {
    if (event.target === els.ruleDialog) {
      els.ruleDialog.close();
    }
  });
  els.pauseDialog.addEventListener("click", (event) => {
    if (event.target === els.pauseDialog) {
      resumeGame();
    }
  });
  els.gameBoard.addEventListener("touchmove", (event) => {
    if (state.isPaused || state.isAutoFilling) {
      return;
    }
    const nextIndex = selectionIndexFromTouchEvent(event);
    if (nextIndex != null && nextIndex !== state.selectedIndex) {
      event.preventDefault();
      state.selectedIndex = nextIndex;
      renderGameBoard();
      persistSession();
    }
  }, { passive: false });
  els.gameBoard.addEventListener("touchstart", (event) => {
    if (state.isPaused || state.isAutoFilling) {
      return;
    }
    const nextIndex = selectionIndexFromTouchEvent(event);
    if (nextIndex != null && nextIndex !== state.selectedIndex) {
      event.preventDefault();
      state.selectedIndex = nextIndex;
      renderGameBoard();
      persistSession();
    }
  }, { passive: false });
  els.noteToggle.addEventListener("click", () => {
    if (state.isPaused || state.isAutoFilling) {
      return;
    }
    state.noteMode = !state.noteMode;
    renderGameBoard();
    persistSession();
  });
  els.clearNotesButton.addEventListener("click", () => {
    clearNotesAtSelection();
  });
  els.eraseCellButton.addEventListener("click", () => {
    eraseCell();
  });

  document.getElementById("clear-next").addEventListener("click", () => {
    els.clearDialog.close();
    startRandomPuzzle();
  });
  document.getElementById("clear-rule").addEventListener("click", () => {
    els.clearDialog.close();
    pauseTimer();
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });
  document.getElementById("clear-home").addEventListener("click", () => {
    els.clearDialog.close();
    pauseTimer();
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });

  window.addEventListener("popstate", async (event) => {
    const screen = event.state?.screen || "rule";
    stopAutoFill();
    if (els.ruleDialog.open) {
      els.ruleDialog.close();
    }
    if (els.pauseDialog.open) {
      els.pauseDialog.close();
    }
    if (screen === "rule") {
      pauseTimer();
      showScreen("rule");
      persistSession();
      return;
    }
    if (screen === "difficulty" && state.currentRule) {
      pauseTimer();
      renderDifficultyScreen();
      showScreen("difficulty");
      persistSession();
      return;
    }
    if (screen === "example" && state.currentDataset) {
      pauseTimer();
      renderExampleScreen();
      showScreen("example");
      persistSession();
      return;
    }
    if (screen === "game" && state.currentPuzzle) {
      showScreen("game");
      if (!state.isPaused) {
        startTimerLoop();
      }
      renderGameBoard();
      persistSession();
      return;
    }
    showScreen("rule");
    persistSession();
  });

  window.addEventListener("pagehide", persistSession);
  window.addEventListener("beforeunload", persistSession);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      stopAutoFill();
      pauseTimer();
      persistSession();
      return;
    }
    if (state.currentScreen === "game" && state.currentPuzzle && !state.isPaused) {
      startTimerLoop();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (screens.game.classList.contains("is-hidden")) {
      return;
    }
    if (state.isAutoFilling) {
      return;
    }
    if (event.key === "Escape" && state.isPaused) {
      event.preventDefault();
      resumeGame();
      return;
    }
    if (state.isPaused) {
      return;
    }
    const [row, col] = coordsFromIndex(state.selectedIndex);
    if (event.key >= "1" && event.key <= "9") {
      event.preventDefault();
      handleValueInput(Number(event.key));
      return;
    }
    if (event.key === "n" || event.key === "N") {
      event.preventDefault();
      state.noteMode = !state.noteMode;
      renderGameBoard();
      persistSession();
      return;
    }
    if (event.key === "c" || event.key === "C") {
      event.preventDefault();
      clearNotesAtSelection();
      return;
    }
    if (event.key === "Backspace" || event.key === "Delete" || event.key === "0") {
      event.preventDefault();
      eraseCell();
      return;
    }

    let nextRow = row;
    let nextCol = col;
    if (event.key === "ArrowUp") {
      nextRow = (row + 8) % 9;
    } else if (event.key === "ArrowDown") {
      nextRow = (row + 1) % 9;
    } else if (event.key === "ArrowLeft") {
      nextCol = (col + 8) % 9;
    } else if (event.key === "ArrowRight") {
      nextCol = (col + 1) % 9;
    } else {
      return;
    }
    event.preventDefault();
    state.selectedIndex = indexFromCoords(nextRow, nextCol);
    renderGameBoard();
    persistSession();
  });
}

async function restoreSession() {
  const snapshot = loadSessionSnapshot();
  if (!snapshot) {
    renderRuleScreen();
    showScreen("rule");
    syncHistory("rule", { replace: true });
    return;
  }

  renderRuleScreen();
  if (!snapshot.currentRuleSlug) {
    showScreen("rule");
    syncHistory("rule", { replace: true });
    return;
  }

  const rule = availableRuleEntries().find((entry) => entry.rule_slug === snapshot.currentRuleSlug);
  if (!rule) {
    showScreen("rule");
    syncHistory("rule", { replace: true });
    return;
  }
  state.currentRule = rule;

  if (!snapshot.currentDifficultyId) {
    renderDifficultyScreen();
    showScreen("difficulty");
    syncHistory("difficulty", { replace: true });
    return;
  }

  const difficulty = state.catalog.difficulties.find((entry) => entry.id === snapshot.currentDifficultyId);
  if (!difficulty) {
    renderDifficultyScreen();
    showScreen("difficulty");
    syncHistory("difficulty", { replace: true });
    return;
  }
  state.currentDifficulty = difficulty;
  state.currentDataset = await loadDataset(difficulty.id, rule.rule_slug);
  state.currentDataset.short_name = displayNameForRuleEntry(
    { rule_slug: rule.rule_slug, rule_mode: state.currentDataset.rule_mode },
    state.currentDataset.short_name,
  );
  state.currentDataset.puzzles = (state.currentDataset.puzzles || []).map((puzzle) => ({
    ...puzzle,
    short_name: displayNameForRuleEntry(
      {
        rule_slug: rule.rule_slug,
        rule_mode: puzzle.rule_mode || state.currentDataset.rule_mode,
      },
      puzzle.short_name,
    ),
  }));

  if (snapshot.currentScreen === "difficulty") {
    renderDifficultyScreen();
    showScreen("difficulty");
    syncHistory("difficulty", { replace: true });
    return;
  }

  renderExampleScreen();
  if (!snapshot.currentPuzzleId) {
    showScreen(snapshot.currentScreen === "game" ? "example" : "example");
    syncHistory("example", { replace: true });
    return;
  }

  const puzzle = state.currentDataset.puzzles.find((entry) => entry.id === snapshot.currentPuzzleId);
  if (!puzzle) {
    showScreen("example");
    syncHistory("example", { replace: true });
    return;
  }

  preparePuzzle(puzzle);
  if (Array.isArray(snapshot.board) && snapshot.board.length === 81) {
    state.board = snapshot.board.map((value) => Number(value) || 0);
  }
  if (Array.isArray(snapshot.notes) && snapshot.notes.length === 81) {
    state.notes = snapshot.notes.map((items) => new Set(Array.isArray(items) ? items.map((value) => Number(value)) : []));
  }
  if (typeof snapshot.selectedIndex === "number") {
    state.selectedIndex = Math.max(0, Math.min(80, snapshot.selectedIndex));
  }
  state.noteMode = Boolean(snapshot.noteMode);
  state.hintCell = Array.isArray(snapshot.hintCell) && snapshot.hintCell.length === 2 ? snapshot.hintCell : null;
  state.elapsedSeconds = typeof snapshot.elapsedSeconds === "number" ? Math.max(0, Math.floor(snapshot.elapsedSeconds)) : 0;
  state.timerStartedAt = null;
  state.isPaused = Boolean(snapshot.isPaused);

  showScreen("game");
  if (!state.isPaused) {
    startTimerLoop();
  } else {
    updateTimerDisplay();
  }
  renderGameBoard();
  syncHistory("game", { replace: true });
}

async function bootstrap() {
  attachIcons();
  attachGlobalEvents();
  try {
    await loadCatalog();
    await restoreSession();
  } catch (error) {
    stopTimerLoop();
    els.ruleList.innerHTML = `<p class="long-copy">${error.message}</p>`;
    showScreen("rule");
    syncHistory("rule", { replace: true });
  }
}

bootstrap();
