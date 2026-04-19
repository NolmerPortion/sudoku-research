const BASE_BG = [252, 251, 248];
const RULE_COLORS = {
  special: [242, 221, 149],
  hyper: [235, 214, 140],
  checker: [247, 231, 173],
  sum: [239, 212, 132],
  cross: [242, 224, 167],
  clone: [221, 228, 168],
};

const state = {
  catalog: null,
  currentDifficulty: null,
  currentRule: null,
  currentDataset: null,
  currentPuzzle: null,
  board: [],
  givens: [],
  notes: [],
  selectedIndex: 0,
  noteMode: false,
  hintCell: null,
  transientError: null,
};

const screens = {
  difficulty: document.getElementById("screen-difficulty"),
  rule: document.getElementById("screen-rule"),
  example: document.getElementById("screen-example"),
  game: document.getElementById("screen-game"),
};

const els = {
  difficultyList: document.getElementById("difficulty-list"),
  ruleList: document.getElementById("rule-list"),
  exampleTitle: document.getElementById("example-title"),
  exampleRuleName: document.getElementById("example-rule-name"),
  exampleDescription: document.getElementById("example-description"),
  exampleBoard: document.getElementById("example-board"),
  gameBoard: document.getElementById("game-board"),
  gameTitle: document.getElementById("game-title"),
  gameRuleChip: document.getElementById("game-rule-chip"),
  statusText: document.getElementById("status-text"),
  guessText: document.getElementById("guess-text"),
  ruleCopy: document.getElementById("rule-copy"),
  keypad: document.getElementById("keypad"),
  noteToggle: document.getElementById("note-toggle"),
  clearDialog: document.getElementById("clear-dialog"),
};

function showScreen(key) {
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

function availableRuleEntriesForDifficulty(difficultyId) {
  const datasets = state.catalog.datasets.filter((item) => item.difficulty_id === difficultyId);
  const available = new Set(datasets.map((item) => item.rule_slug));
  return state.catalog.rules.filter((rule) => available.has(rule.rule_slug));
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
    throw new Error("選択した難易度とルールのデータセットが見つかりません。");
  }
  const response = await fetch(`./data/${entry.path}`);
  if (!response.ok) {
    throw new Error(`データセットを読み込めませんでした: ${entry.path}`);
  }
  return response.json();
}

function renderDifficultyScreen() {
  els.difficultyList.innerHTML = "";
  const available = new Set(state.catalog.datasets.map((item) => item.difficulty_id));
  for (const difficulty of state.catalog.difficulties) {
    if (!available.has(difficulty.id)) {
      continue;
    }
    const button = document.createElement("button");
    button.className = "choice-card";
    button.innerHTML = `
      <strong>${difficulty.label}</strong>
      <p>最小手がかり数 ${difficulty.min_clues} のデータセットから出題します。</p>
    `;
    button.addEventListener("click", () => {
      state.currentDifficulty = difficulty;
      renderRuleScreen();
      showScreen("rule");
    });
    els.difficultyList.appendChild(button);
  }
}

function renderRuleScreen() {
  els.ruleList.innerHTML = "";
  const rules = availableRuleEntriesForDifficulty(state.currentDifficulty.id);
  for (const rule of rules) {
    const button = document.createElement("button");
    button.className = "choice-card";
    button.innerHTML = `
      <strong>${rule.short_name}</strong>
      <p>${rule.description_ja}</p>
    `;
    button.addEventListener("click", async () => {
      state.currentRule = rule;
      state.currentDataset = await loadDataset(state.currentDifficulty.id, rule.rule_slug);
      renderExampleScreen();
      showScreen("example");
    });
    els.ruleList.appendChild(button);
  }
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
    rgb = blendRgb(rgb, RULE_COLORS.special, 0.36);
  }
  if (visualSet(visual.hyper_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.hyper, 0.28);
  }
  if (visualSet(visual.checkerboard_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.checker, 0.24);
  }
  if (visualSet(visual.sum_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.sum, 0.33);
  }
  if (visualSet(visual.cross_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.cross, 0.26);
  }
  if (visualSet(visual.clone_cells).has(key)) {
    rgb = blendRgb(rgb, RULE_COLORS.clone, 0.26);
  }
  if (!isExample && selected && isPeerCell(visual, selected[0], selected[1], row, col)) {
    rgb = blendRgb(rgb, [215, 171, 58], 0.34);
  }
  if (hint && hint[0] === row && hint[1] === col) {
    rgb = blendRgb(rgb, [233, 188, 69], 0.48);
  }
  if (selected && selected[0] === row && selected[1] === col) {
    rgb = blendRgb(rgb, [233, 188, 69], 0.62);
  }
  if (error && error[0] === row && error[1] === col) {
    rgb = blendRgb(rgb, [211, 87, 87], 0.52);
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

function renderExampleScreen() {
  const dataset = state.currentDataset;
  els.exampleTitle.textContent = `${dataset.short_name} の説明`;
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

function setGuessMessage(text, cell = null) {
  els.guessText.textContent = text;
  state.transientError = cell;
  if (cell) {
    window.setTimeout(() => {
      resetTransientError();
      renderGameBoard();
    }, 900);
  }
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

  const step = nextExpectedStep();
  if (!step) {
    return;
  }
  if (step.row !== row || step.col !== col) {
    setGuessMessage("この手順では、そのマスを開くとあてずっぽう扱いになります。", [row, col]);
    renderGameBoard();
    return;
  }
  if (value !== step.value) {
    setGuessMessage("その数字は正しくありません。", [row, col]);
    renderGameBoard();
    return;
  }

  state.board[index] = value;
  state.notes[index].clear();
  clearRelatedNotes(row, col, value);
  state.hintCell = null;
  els.guessText.textContent = "";
  renderGameBoard();
  if (!nextExpectedStep()) {
    els.clearDialog.showModal();
  }
}

function eraseCell() {
  const index = state.selectedIndex;
  if (state.givens[index]) {
    return;
  }
  state.board[index] = 0;
  renderGameBoard();
}

function clearNotesAtSelection() {
  const index = state.selectedIndex;
  state.notes[index].clear();
  renderGameBoard();
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
    button.innerHTML = remaining > 0 ? `${value}<span>残り ${remaining}</span>` : "&nbsp;";
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
  const step = nextExpectedStep();
  els.statusText.textContent = step
    ? `次に進める位置を一つだけ前計算しています。現在の手は (${step.row + 1}, ${step.col + 1}) です。`
    : "盤面が完成しました。";
  renderNumberButtons();
  els.noteToggle.textContent = state.noteMode ? "メモ ON" : "メモ";
}

function preparePuzzle(puzzle) {
  state.currentPuzzle = puzzle;
  state.board = parseGrid(puzzle.puzzle_string);
  state.givens = state.board.map((value) => value !== 0);
  state.notes = Array.from({ length: 81 }, () => new Set());
  state.selectedIndex = state.board.findIndex((value) => value === 0);
  if (state.selectedIndex < 0) {
    state.selectedIndex = 0;
  }
  state.noteMode = false;
  state.hintCell = null;
  state.transientError = null;
  els.gameTitle.textContent = `${state.currentDifficulty.label} / ${puzzle.short_name}`;
  els.gameRuleChip.textContent = puzzle.short_name;
  els.ruleCopy.textContent = state.currentDataset.description_ja;
  renderGameBoard();
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
}

function attachGlobalEvents() {
  document.getElementById("back-to-difficulty").addEventListener("click", () => showScreen("difficulty"));
  document.getElementById("back-to-rule").addEventListener("click", () => showScreen("rule"));
  document.getElementById("start-puzzle").addEventListener("click", startRandomPuzzle);
  document.getElementById("menu-home").addEventListener("click", () => showScreen("difficulty"));
  document.getElementById("hint-button").addEventListener("click", () => {
    const step = nextExpectedStep();
    if (!step) {
      return;
    }
    state.hintCell = [step.row, step.col];
    renderGameBoard();
  });
  document.getElementById("rule-button").addEventListener("click", () => showScreen("example"));
  els.noteToggle.addEventListener("click", () => {
    state.noteMode = !state.noteMode;
    renderGameBoard();
  });
  document.getElementById("clear-notes").addEventListener("click", clearNotesAtSelection);
  document.getElementById("erase-cell").addEventListener("click", eraseCell);

  document.getElementById("clear-next").addEventListener("click", () => {
    els.clearDialog.close();
    startRandomPuzzle();
  });
  document.getElementById("clear-rule").addEventListener("click", () => {
    els.clearDialog.close();
    showScreen("rule");
  });
  document.getElementById("clear-home").addEventListener("click", () => {
    els.clearDialog.close();
    showScreen("difficulty");
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
  });
}

async function bootstrap() {
  attachGlobalEvents();
  try {
    await loadCatalog();
    renderDifficultyScreen();
    showScreen("difficulty");
  } catch (error) {
    els.difficultyList.innerHTML = `<p class="long-copy">${error.message}</p>`;
    showScreen("difficulty");
  }
}

bootstrap();
