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
  rule: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 4h10a3 3 0 0 1 3 3v13H9a3 3 0 0 0-3 3z"></path>
      <path d="M6 4v16a3 3 0 0 0 3 3"></path>
    </svg>
  `,
  hint: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 18h6"></path>
      <path d="M10 22h4"></path>
      <path d="M8 14a6 6 0 1 1 8 0c-1 1-1.5 2-1.5 3h-5C9.5 16 9 15 8 14z"></path>
    </svg>
  `,
  note: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 3h9l3 3v15H6z"></path>
      <path d="M15 3v4h4"></path>
      <path d="M9 11h6"></path>
      <path d="M9 15h6"></path>
    </svg>
  `,
  clearNotes: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7h16"></path>
      <path d="M9 7V4h6v3"></path>
      <path d="M7 7l1 12h8l1-12"></path>
      <path d="M10 11v5"></path>
      <path d="M14 11v5"></path>
    </svg>
  `,
  erase: `
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 15l8-10 8 10-4 5H8z"></path>
      <path d="M10 20h10"></path>
    </svg>
  `,
};

const DISPLAY_NAMES = {
  standard: "Standard",
  anti_close_adjacent_3: "D(distance)",
  bishop_meet_digits: "N(net)",
  checkerboard_odd: "O(odd)",
  clone_regions_set_equal: "M(mirror)",
  cross_monotone: "X(cross)",
  hyper_3x3: "H(hyper)",
  hyper3x3: "H(hyper)",
  l_tromino_sum: "L(l tromino)",
  local_consecutive_exists: "T(touch)",
  special_monotone_3x3: "M(matrices)",
};

const SESSION_STORAGE_KEY = "sudoku_variants_session_v1";

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
  gameRuleChip: document.getElementById("game-rule-chip"),
  statusLine: document.getElementById("status-line"),
  keypad: document.getElementById("keypad"),
  noteToggle: document.getElementById("note-toggle"),
  ruleButton: document.getElementById("rule-button"),
  hintButton: document.getElementById("hint-button"),
  clearNotesButton: document.getElementById("clear-notes"),
  eraseCellButton: document.getElementById("erase-cell"),
  menuHome: document.getElementById("menu-home"),
  clearDialog: document.getElementById("clear-dialog"),
  ruleDialog: document.getElementById("rule-dialog"),
  dialogRuleChip: document.getElementById("dialog-rule-chip"),
  dialogRuleTitle: document.getElementById("dialog-rule-title"),
  dialogRuleCopy: document.getElementById("dialog-rule-copy"),
};

function showScreen(key) {
  state.currentScreen = key;
  for (const [name, node] of Object.entries(screens)) {
    node.classList.toggle("is-hidden", name !== key);
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

function decorateRule(rule) {
  return {
    ...rule,
    short_name: displayNameForRule(rule.rule_mode || rule.rule_slug, rule.short_name),
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
  for (const rule of availableRuleEntries()) {
    const button = document.createElement("button");
    button.className = "choice-card";
    button.innerHTML = `
      <strong>${rule.short_name}</strong>
      <p>${rule.description_ja}</p>
    `;
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
    button.className = "choice-card";
    button.innerHTML = `
      <strong>${difficulty.label}</strong>
      <p>Min clues ${difficulty.min_clues}</p>
    `;
    button.addEventListener("click", async () => {
      state.currentDifficulty = difficulty;
      state.currentDataset = await loadDataset(difficulty.id, state.currentRule.rule_slug);
      state.currentDataset.short_name = displayNameForRule(
        state.currentDataset.rule_mode || state.currentRule.rule_mode,
        state.currentDataset.short_name,
      );
      state.currentDataset.puzzles = (state.currentDataset.puzzles || []).map((puzzle) => ({
        ...puzzle,
        short_name: displayNameForRule(
          puzzle.rule_mode || state.currentDataset.rule_mode,
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
  els.exampleDescription.textContent = dataset.description_ja;
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

function resetTransientError() {
  state.transientError = null;
}

function handleValueInput(value) {
  if (!state.currentPuzzle) {
    return;
  }
  const index = state.selectedIndex;
  const [row, col] = coordsFromIndex(index);
  if (state.givens[index]) {
    return;
  }

  if (state.noteMode) {
    if (state.board[index] !== 0) {
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

  const correctValue = Number(state.currentPuzzle.solution_string[index]);
  if (value !== correctValue) {
    state.transientError = [row, col];
    renderGameBoard();
    window.setTimeout(() => {
      resetTransientError();
      renderGameBoard();
    }, 900);
    return;
  }

  state.board[index] = value;
  state.notes[index].clear();
  clearRelatedNotes(row, col, value);
  state.hintCell = null;
  renderGameBoard();
  persistSession();
  if (state.board.every((cell) => cell !== 0)) {
    els.clearDialog.showModal();
  }
}

function eraseCell() {
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
  els.statusLine.textContent = `${state.currentDifficulty.label} / ${state.currentPuzzle.short_name}`;
  els.noteToggle.classList.toggle("is-active", state.noteMode);
  renderNumberButtons();
}

function preparePuzzle(puzzle) {
  state.currentPuzzle = puzzle;
  state.board = parseGrid(puzzle.puzzle_string);
  state.givens = state.board.map((value) => value !== 0);
  state.notes = Array.from({ length: 81 }, () => new Set());
  state.selectedIndex = Math.max(0, state.board.findIndex((value) => value === 0));
  state.noteMode = false;
  state.hintCell = null;
  state.transientError = null;
  els.gameTitle.textContent = state.currentDifficulty.label;
  els.gameRuleChip.textContent = displayNameForRule(
    puzzle.rule_mode || state.currentDataset?.rule_mode,
    puzzle.short_name,
  );
  renderGameBoard();
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

function openRuleDialog() {
  if (!state.currentDataset) {
    return;
  }
  els.dialogRuleChip.textContent = displayNameForRule(
    state.currentDataset.rule_mode || state.currentRule?.rule_mode,
    state.currentDataset.short_name,
  );
  els.dialogRuleTitle.textContent = "Rule";
  els.dialogRuleCopy.textContent = state.currentDataset.description_ja;
  els.ruleDialog.showModal();
}

function attachIcons() {
  els.ruleButton.innerHTML = ICONS.rule;
  els.hintButton.innerHTML = ICONS.hint;
  els.noteToggle.innerHTML = ICONS.note;
  els.clearNotesButton.innerHTML = ICONS.clearNotes;
  els.eraseCellButton.innerHTML = ICONS.erase;
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
  document.getElementById("start-puzzle").addEventListener("click", startRandomPuzzle);
  els.menuHome.addEventListener("click", () => {
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });
  els.hintButton.addEventListener("click", () => {
    const step = nextExpectedStep();
    if (!step) {
      return;
    }
    state.hintCell = [step.row, step.col];
    renderGameBoard();
    persistSession();
  });
  els.ruleButton.addEventListener("click", openRuleDialog);
  document.getElementById("close-rule-dialog").addEventListener("click", () => els.ruleDialog.close());
  els.noteToggle.addEventListener("click", () => {
    state.noteMode = !state.noteMode;
    renderGameBoard();
    persistSession();
  });
  els.clearNotesButton.addEventListener("click", clearNotesAtSelection);
  els.eraseCellButton.addEventListener("click", eraseCell);

  document.getElementById("clear-next").addEventListener("click", () => {
    els.clearDialog.close();
    startRandomPuzzle();
  });
  document.getElementById("clear-rule").addEventListener("click", () => {
    els.clearDialog.close();
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });
  document.getElementById("clear-home").addEventListener("click", () => {
    els.clearDialog.close();
    showScreen("rule");
    syncHistory("rule");
    persistSession();
  });

  window.addEventListener("popstate", async (event) => {
    const screen = event.state?.screen || "rule";
    if (els.ruleDialog.open) {
      els.ruleDialog.close();
    }
    if (screen === "rule") {
      showScreen("rule");
      persistSession();
      return;
    }
    if (screen === "difficulty" && state.currentRule) {
      renderDifficultyScreen();
      showScreen("difficulty");
      persistSession();
      return;
    }
    if (screen === "example" && state.currentDataset) {
      renderExampleScreen();
      showScreen("example");
      persistSession();
      return;
    }
    if (screen === "game" && state.currentPuzzle) {
      showScreen("game");
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
      persistSession();
    }
  });

  window.addEventListener("keydown", (event) => {
    if (screens.game.classList.contains("is-hidden")) {
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
  state.currentDataset.short_name = displayNameForRule(
    state.currentDataset.rule_mode || state.currentRule.rule_mode,
    state.currentDataset.short_name,
  );
  state.currentDataset.puzzles = (state.currentDataset.puzzles || []).map((puzzle) => ({
    ...puzzle,
    short_name: displayNameForRule(
      puzzle.rule_mode || state.currentDataset.rule_mode,
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

  showScreen("game");
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
    els.ruleList.innerHTML = `<p class="long-copy">${error.message}</p>`;
    showScreen("rule");
    syncHistory("rule", { replace: true });
  }
}

bootstrap();
