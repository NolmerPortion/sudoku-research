from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from check_uniqueness import parse_pattern_mask, parse_puzzle_string
from rule_visuals import build_rule_explanation, build_rule_visual_state


Grid9 = list[list[int]]


def grid_from_json_value(value: Any) -> Grid9 | None:
    if not isinstance(value, list) or len(value) != 9:
        return None

    grid: Grid9 = []
    for row in value:
        if not isinstance(row, list) or len(row) != 9:
            return None
        out_row: list[int] = []
        for cell in row:
            if not isinstance(cell, int):
                return None
            out_row.append(cell)
        grid.append(out_row)
    return grid


def grid_to_string(grid: Grid9) -> str:
    return "".join(str(grid[r][c]) for r in range(9) for c in range(9))


def normalize_puzzle_entry(raw: Any, fallback_pattern_mask: str | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    puzzle_string = raw.get("puzzle_string")
    solution_string = raw.get("solution_string")
    puzzle_grid = grid_from_json_value(raw.get("puzzle_grid"))
    solution_grid = grid_from_json_value(raw.get("solution_grid"))

    if not isinstance(puzzle_string, str) and puzzle_grid is not None:
        puzzle_string = grid_to_string(puzzle_grid)
    if not isinstance(solution_string, str) and solution_grid is not None:
        solution_string = grid_to_string(solution_grid)

    if isinstance(puzzle_string, str):
        puzzle_grid = parse_puzzle_string(puzzle_string)
    if isinstance(solution_string, str):
        solution_grid = parse_puzzle_string(solution_string)

    if puzzle_grid is None or solution_grid is None:
        return None

    pattern_mask = raw.get("pattern_mask")
    if not isinstance(pattern_mask, str):
        pattern_mask = raw.get("pattern_mask_string")
    if not isinstance(pattern_mask, str):
        pattern_mask = fallback_pattern_mask
    if not isinstance(pattern_mask, str):
        return None

    return {
        "pattern_mask": pattern_mask,
        "puzzle_grid": puzzle_grid,
        "puzzle_string": grid_to_string(puzzle_grid),
        "solution_grid": solution_grid,
        "solution_string": grid_to_string(solution_grid),
        "rule_mode": raw.get("rule_mode", ""),
        "rule_name": raw.get("rule_name", ""),
        "rules": raw.get("rules", []),
        "source_file": raw.get("source_file", ""),
        "source_file_name": raw.get("source_file_name", ""),
        "clue_count": raw.get("clue_count"),
    }


def collect_puzzle_entries_from_json(data: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_candidate(raw: Any, fallback_pattern_mask: str | None = None) -> None:
        normalized = normalize_puzzle_entry(raw, fallback_pattern_mask)
        if normalized is None:
            return
        key = (normalized["pattern_mask"], normalized["puzzle_string"])
        if key in seen:
            return
        seen.add(key)
        entries.append(normalized)

    if isinstance(data, dict):
        root_pattern_mask = data.get("pattern_mask")
        if not isinstance(root_pattern_mask, str):
            root_pattern_mask = data.get("pattern_mask_string")

        add_candidate(data, root_pattern_mask if isinstance(root_pattern_mask, str) else None)

        results = data.get("results")
        if isinstance(results, list):
            for item in results:
                add_candidate(item, root_pattern_mask if isinstance(root_pattern_mask, str) else None)

    return entries


class SudokuBoardWidget(QWidget):
    noteModeChanged = Signal(bool)
    puzzleSolved = Signal()
    boardStateChanged = Signal()
    historyChanged = Signal(bool, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.pattern_mask = "000000000"
        self.special_positions: set[tuple[int, int]] = set()
        self.rules: list[dict[str, Any]] = []
        self.visual_state = build_rule_visual_state(self.pattern_mask, self.rules)
        self.givens: Grid9 = [[0] * 9 for _ in range(9)]
        self.solution_grid: Grid9 = [[0] * 9 for _ in range(9)]
        self.current_grid: Grid9 = [[0] * 9 for _ in range(9)]
        self.notes: list[list[set[int]]] = [[set() for _ in range(9)] for _ in range(9)]
        self.selected_row = 0
        self.selected_col = 0
        self.note_mode = False
        self._input_locked = False
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []

        self._font_large = QFont("Segoe UI", 22)
        self._font_given = QFont("Segoe UI Semibold", 22)
        self._font_note = QFont("Segoe UI", 9)

    def sizeHint(self) -> QSize:
        return QSize(760, 760)

    def minimumSizeHint(self) -> QSize:
        return QSize(420, 420)

    def set_puzzle(self, entry: dict[str, Any]) -> None:
        self.pattern_mask = entry["pattern_mask"]
        self.special_positions = parse_pattern_mask(self.pattern_mask)
        self.rules = [rule for rule in entry.get("rules", []) if isinstance(rule, dict)]
        self.visual_state = build_rule_visual_state(self.pattern_mask, self.rules)
        self.solution_grid = [row[:] for row in entry["solution_grid"]]
        self.current_grid = [row[:] for row in entry["puzzle_grid"]]
        self.givens = [row[:] for row in entry["puzzle_grid"]]
        self.notes = [[set() for _ in range(9)] for _ in range(9)]
        self.selected_row = 0
        self.selected_col = 0
        self.note_mode = False
        self._input_locked = False
        self._undo_stack = []
        self._redo_stack = []
        self.update()
        self.setFocus()
        self.boardStateChanged.emit()
        self.historyChanged.emit(False, False)

    def set_note_mode(self, enabled: bool) -> None:
        if self.note_mode == enabled:
            return
        self.note_mode = enabled
        self.noteModeChanged.emit(self.note_mode)
        self.update()

    def toggle_note_mode(self) -> None:
        self.set_note_mode(not self.note_mode)

    def set_input_locked(self, locked: bool) -> None:
        self._input_locked = locked

    def size_for_board(self) -> tuple[int, int, float, int]:
        square = min(self.width(), self.height())
        board_x = (self.width() - square) // 2
        board_y = (self.height() - square) // 2
        cell = square / 9.0
        return board_x, board_y, cell, square

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        board_x, board_y, cell, square = self.size_for_board()
        painter.fillRect(self.rect(), QColor("#f6f6f6"))

        for r in range(9):
            for c in range(9):
                rect = QRect(
                    round(board_x + c * cell),
                    round(board_y + r * cell),
                    round(cell),
                    round(cell),
                )
                painter.fillRect(rect, self._cell_background_color(r, c))

        self._draw_cross_overlays(painter, board_x, board_y, cell)

        for r in range(9):
            for c in range(9):
                rect = QRect(
                    round(board_x + c * cell),
                    round(board_y + r * cell),
                    round(cell),
                    round(cell),
                )
                value = self.current_grid[r][c]
                if value != 0:
                    is_given = self.givens[r][c] != 0
                    painter.setPen(QColor("#111111") if is_given else QColor("#1f5ed9"))
                    painter.setFont(self._font_given if is_given else self._font_large)
                    painter.drawText(rect, Qt.AlignCenter, str(value))
                elif self.notes[r][c]:
                    painter.setPen(QColor("#555555"))
                    painter.setFont(self._font_note)
                    mini_w = rect.width() / 3.0
                    mini_h = rect.height() / 3.0
                    for note in sorted(self.notes[r][c]):
                        nr = (note - 1) // 3
                        nc = (note - 1) % 3
                        mini_rect = QRect(
                            round(rect.x() + nc * mini_w),
                            round(rect.y() + nr * mini_h),
                            round(mini_w),
                            round(mini_h),
                        )
                        painter.drawText(mini_rect, Qt.AlignCenter, str(note))

        self._draw_sum_region_labels(painter, board_x, board_y, cell)

        thin_pen = QPen(QColor("#444444"))
        thin_pen.setWidth(1)
        thick_pen = QPen(QColor("#111111"))
        thick_pen.setWidth(3)

        for index in range(10):
            painter.setPen(thick_pen if index % 3 == 0 else thin_pen)
            offset = round(index * cell)
            painter.drawLine(board_x + offset, board_y, board_x + offset, board_y + square)
            painter.drawLine(board_x, board_y + offset, board_x + square, board_y + offset)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if self._input_locked:
            return
        cell = self._cell_at_point(event.position().toPoint())
        if cell is None:
            return
        self.selected_row, self.selected_col = cell
        self.setFocus()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._input_locked:
            return

        key = event.key()
        if key == Qt.Key_N:
            self.toggle_note_mode()
            return
        if key == Qt.Key_C:
            self.clear_selected_notes()
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._move_selection(key)
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_0):
            self.clear_selected_cell()
            return
        if Qt.Key_1 <= key <= Qt.Key_9:
            self.input_value(key - Qt.Key_0)
            return
        super().keyPressEvent(event)

    def input_value(self, value: int) -> None:
        if self._input_locked:
            return

        row = self.selected_row
        col = self.selected_col
        if self.givens[row][col] != 0:
            return

        if self.note_mode:
            new_value = self.current_grid[row][col]
            new_notes = set(self.notes[row][col])
            if new_value != 0:
                new_value = 0
            if value in new_notes:
                new_notes.remove(value)
            else:
                new_notes.add(value)
            if new_value == self.current_grid[row][col] and new_notes == self.notes[row][col]:
                return
            self._push_undo_state()
            self.current_grid[row][col] = new_value
            self.notes[row][col] = new_notes
        else:
            if self.current_grid[row][col] == value and not self.notes[row][col]:
                return
            self._push_undo_state()
            self.current_grid[row][col] = value
            self.notes[row][col].clear()
            if value == self.solution_grid[row][col]:
                self._clear_peer_notes(row, col, value)

        self._after_board_change()
        if self._is_solved():
            self.puzzleSolved.emit()

    def clear_selected_cell(self) -> None:
        if self._input_locked:
            return
        row = self.selected_row
        col = self.selected_col
        if self.givens[row][col] != 0:
            return
        if self.current_grid[row][col] == 0 and not self.notes[row][col]:
            return
        self._push_undo_state()
        self.current_grid[row][col] = 0
        self.notes[row][col].clear()
        self._after_board_change()

    def clear_selected_notes(self) -> None:
        if self._input_locked:
            return
        row = self.selected_row
        col = self.selected_col
        if not self.notes[row][col]:
            return
        self._push_undo_state()
        self.notes[row][col].clear()
        self._after_board_change()

    def undo(self) -> None:
        if self._input_locked or not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self._restore_snapshot(self._undo_stack.pop())
        self._after_board_change()

    def redo(self) -> None:
        if self._input_locked or not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self._restore_snapshot(self._redo_stack.pop())
        self._after_board_change()

    def remaining_counts(self) -> dict[int, int]:
        correct_counts = {value: 0 for value in range(1, 10)}
        for r in range(9):
            for c in range(9):
                value = self.current_grid[r][c]
                if value != 0 and value == self.solution_grid[r][c]:
                    correct_counts[value] += 1
        return {value: 9 - correct_counts[value] for value in range(1, 10)}

    def remaining_unsolved_count(self) -> int:
        return sum(
            1
            for r in range(9)
            for c in range(9)
            if self.current_grid[r][c] != self.solution_grid[r][c]
        )

    def begin_autofill_session(self) -> None:
        self._push_undo_state()

    def apply_solution_step(self) -> bool:
        for row in range(9):
            for col in range(9):
                if self.current_grid[row][col] == self.solution_grid[row][col]:
                    continue
                if self.givens[row][col] != 0:
                    continue
                value = self.solution_grid[row][col]
                self.current_grid[row][col] = value
                self.notes[row][col].clear()
                self._clear_peer_notes(row, col, value)
                self._after_board_change()
                if self._is_solved():
                    self.puzzleSolved.emit()
                return True
        return False

    def _cell_background_color(self, row: int, col: int) -> QColor:
        bg = self._rule_background_color(row, col)
        if self._is_wrong_cell(row, col):
            bg = self._blend_colors(bg, QColor("#ffd6d6"), 0.68)
        if row == self.selected_row and col == self.selected_col:
            overlay = QColor("#ffb3b3") if self._is_wrong_cell(row, col) else QColor("#ffe169")
            return self._blend_colors(bg, overlay, 0.84)
        if self._is_selection_peer(row, col):
            overlay = QColor("#ffe1e1") if self._is_wrong_cell(row, col) else QColor("#f0f0f0")
            return self._blend_colors(bg, overlay, 0.58)
        return bg

    def _rule_background_color(self, row: int, col: int) -> QColor:
        if (row, col) in self.visual_state["special_cells"]:
            return QColor("#fff3b0")
        if (row, col) in self.visual_state["hyper_cells"]:
            return QColor("#fff6c9")
        if (row, col) in self.visual_state["checkerboard_cells"]:
            return QColor("#fffbe8")
        if (row, col) in self.visual_state["sum_cells"]:
            return QColor("#ffe9bf")
        if (row, col) in self.visual_state["clone_cells"]:
            return QColor("#eef0b8")
        if (row, col) in self.visual_state["cross_centers"]:
            return QColor("#ffe38a")
        if (row, col) in self.visual_state["cross_cells"]:
            return QColor("#fff2c7")
        return QColor("#ffffff")

    def _is_selection_peer(self, row: int, col: int) -> bool:
        if row == self.selected_row or col == self.selected_col:
            return True
        if self.visual_state.get("has_bishop_rule"):
            return abs(row - self.selected_row) == abs(col - self.selected_col)
        return False

    def _blend_colors(self, base: QColor, overlay: QColor, overlay_ratio: float) -> QColor:
        overlay_ratio = max(0.0, min(1.0, overlay_ratio))
        base_ratio = 1.0 - overlay_ratio
        return QColor(
            round(base.red() * base_ratio + overlay.red() * overlay_ratio),
            round(base.green() * base_ratio + overlay.green() * overlay_ratio),
            round(base.blue() * base_ratio + overlay.blue() * overlay_ratio),
        )

    def _draw_cross_overlays(self, painter: QPainter, board_x: int, board_y: int, cell: float) -> None:
        if not self.visual_state["crosses"]:
            return
        pen = QPen(QColor("#d3a500"))
        pen.setWidth(2)
        painter.setPen(pen)
        for cross in self.visual_state["crosses"]:
            center = cross.get("center")
            if not isinstance(center, list | tuple) or len(center) != 2:
                continue
            row = int(center[0])
            col = int(center[1])
            cx = board_x + (col + 0.5) * cell
            cy = board_y + (row + 0.5) * cell
            for delta_row, delta_col, length_key in (
                (-1, 0, "up_len"),
                (1, 0, "down_len"),
                (0, -1, "left_len"),
                (0, 1, "right_len"),
            ):
                length = int(cross.get(length_key, 0))
                if length <= 0:
                    continue
                ex = board_x + (col + 0.5 + delta_col * length) * cell
                ey = board_y + (row + 0.5 + delta_row * length) * cell
                painter.drawLine(round(cx), round(cy), round(ex), round(ey))

    def _draw_sum_region_labels(self, painter: QPainter, board_x: int, board_y: int, cell: float) -> None:
        if not self.visual_state["sum_regions"]:
            return
        painter.setPen(QColor("#7a5b00"))
        painter.setFont(QFont("Segoe UI", 8))
        for region in self.visual_state["sum_regions"]:
            cells = region.get("cells", [])
            if not cells:
                continue
            row = min(int(cell_row) for cell_row, _ in cells)
            col = min(int(cell_col) for _, cell_col in cells)
            rect = QRect(
                round(board_x + col * cell + 4),
                round(board_y + row * cell + 2),
                round(cell * 1.7),
                round(cell * 0.45),
            )
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, str(int(region["target_sum"])))

    def _cell_at_point(self, point: QPoint) -> tuple[int, int] | None:
        board_x, board_y, cell, square = self.size_for_board()
        if not (board_x <= point.x() < board_x + square and board_y <= point.y() < board_y + square):
            return None
        col = int((point.x() - board_x) / cell)
        row = int((point.y() - board_y) / cell)
        return row, col

    def _move_selection(self, key: int) -> None:
        if key == Qt.Key_Left:
            self.selected_col = (self.selected_col - 1) % 9
        elif key == Qt.Key_Right:
            self.selected_col = (self.selected_col + 1) % 9
        elif key == Qt.Key_Up:
            self.selected_row = (self.selected_row - 1) % 9
        elif key == Qt.Key_Down:
            self.selected_row = (self.selected_row + 1) % 9
        self.update()

    def _is_solved(self) -> bool:
        return self.current_grid == self.solution_grid

    def _is_wrong_cell(self, row: int, col: int) -> bool:
        value = self.current_grid[row][col]
        return value != 0 and value != self.solution_grid[row][col]

    def _clear_peer_notes(self, row: int, col: int, value: int) -> None:
        for index in range(9):
            if index != col:
                self.notes[row][index].discard(value)
            if index != row:
                self.notes[index][col].discard(value)

        block_row = (row // 3) * 3
        block_col = (col // 3) * 3
        for r in range(block_row, block_row + 3):
            for c in range(block_col, block_col + 3):
                if (r, c) != (row, col):
                    self.notes[r][c].discard(value)

    def _snapshot(self) -> dict[str, Any]:
        return {
            "current_grid": [row[:] for row in self.current_grid],
            "notes": [[set(cell) for cell in row] for row in self.notes],
            "selected_row": self.selected_row,
            "selected_col": self.selected_col,
        }

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.current_grid = [row[:] for row in snapshot["current_grid"]]
        self.notes = [[set(cell) for cell in row] for row in snapshot["notes"]]
        self.selected_row = snapshot["selected_row"]
        self.selected_col = snapshot["selected_col"]

    def _push_undo_state(self) -> None:
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def _after_board_change(self) -> None:
        self.update()
        self.boardStateChanged.emit()
        self.historyChanged.emit(bool(self._undo_stack), bool(self._redo_stack))


class PlayerWindow(QMainWindow):
    def __init__(self, initial_json_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Sudoku Variants Demo")
        self.resize(900, 980)

        self.loaded_entries: list[dict[str, Any]] = []
        self.current_entry: dict[str, Any] | None = None
        self.loaded_path: Path | None = None
        self.number_buttons: dict[int, QPushButton] = {}
        self.autofill_enabled = True
        self.autofill_running = False
        self.autofill_timer = QTimer(self)
        self.autofill_timer.setInterval(400)
        self.autofill_timer.timeout.connect(self._run_autofill_step)

        self._build_ui()
        self._apply_style()

        if initial_json_path:
            self.load_json_file(Path(initial_json_path))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        puzzle_tab = QWidget()
        puzzle_root = QVBoxLayout(puzzle_tab)
        puzzle_root.setContentsMargins(0, 0, 0, 0)
        puzzle_root.setSpacing(12)
        self.tabs.addTab(puzzle_tab, "Puzzle")

        rules_tab = QWidget()
        rules_root = QVBoxLayout(rules_tab)
        rules_root.setContentsMargins(0, 0, 0, 0)
        rules_root.setSpacing(8)
        self.tabs.addTab(rules_tab, "Rules")

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        puzzle_root.addLayout(top_bar)

        self.load_button = QPushButton("Load JSON")
        self.load_button.setFocusPolicy(Qt.NoFocus)
        self.load_button.clicked.connect(self._open_json_dialog)
        top_bar.addWidget(self.load_button)

        self.random_button = QPushButton("Random Puzzle")
        self.random_button.setFocusPolicy(Qt.NoFocus)
        self.random_button.clicked.connect(self.choose_random_puzzle)
        self.random_button.setEnabled(False)
        top_bar.addWidget(self.random_button)

        self.note_button = QPushButton("Note: OFF")
        self.note_button.setCheckable(True)
        self.note_button.setFocusPolicy(Qt.NoFocus)
        self.note_button.toggled.connect(self._set_note_mode_from_button)
        top_bar.addWidget(self.note_button)

        self.autofill_button = QPushButton("Auto-fill <= 9: ON")
        self.autofill_button.setCheckable(True)
        self.autofill_button.setChecked(True)
        self.autofill_button.setFocusPolicy(Qt.NoFocus)
        self.autofill_button.toggled.connect(self._set_autofill_enabled)
        top_bar.addWidget(self.autofill_button)

        self.undo_button = QPushButton("Undo")
        self.undo_button.setFocusPolicy(Qt.NoFocus)
        self.undo_button.clicked.connect(self._undo)
        self.undo_button.setEnabled(False)
        top_bar.addWidget(self.undo_button)

        self.redo_button = QPushButton("Redo")
        self.redo_button.setFocusPolicy(Qt.NoFocus)
        self.redo_button.clicked.connect(self._redo)
        self.redo_button.setEnabled(False)
        top_bar.addWidget(self.redo_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setFocusPolicy(Qt.NoFocus)
        self.clear_button.clicked.connect(self._clear_selected_cell)
        top_bar.addWidget(self.clear_button)

        top_bar.addStretch(1)

        self.status_label = QLabel("Load a generated JSON file to pick a random puzzle.")
        puzzle_root.addWidget(self.status_label)

        self.board = SudokuBoardWidget()
        self.board.noteModeChanged.connect(self._sync_note_button)
        self.board.puzzleSolved.connect(self._on_puzzle_solved)
        self.board.boardStateChanged.connect(self._update_number_buttons)
        self.board.boardStateChanged.connect(self._maybe_start_autofill)
        self.board.historyChanged.connect(self._update_history_buttons)
        puzzle_root.addWidget(self.board, 1)

        keypad_row = QHBoxLayout()
        keypad_row.setSpacing(8)
        puzzle_root.addLayout(keypad_row)

        for value in range(1, 10):
            button = QPushButton(str(value))
            button.setMinimumHeight(56)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda checked=False, n=value: self._input_from_button(n))
            keypad_row.addWidget(button)
            self.number_buttons[value] = button

        rules_help = QLabel("Open this tab to see the rule explanation for the currently loaded puzzle.")
        rules_root.addWidget(rules_help)

        self.rule_explanation_edit = QPlainTextEdit()
        self.rule_explanation_edit.setReadOnly(True)
        self.rule_explanation_edit.setPlainText("Load a generated JSON file to see the rule explanation.")
        rules_root.addWidget(self.rule_explanation_edit, 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f7f7f7;
                color: #111111;
            }
            QPushButton {
                background: #ffffff;
                color: #111111;
                border: 1px solid #222222;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 16px;
            }
            QPushButton:hover {
                background: #fff6cc;
            }
            QPushButton:checked {
                background: #ffe169;
            }
            QPushButton:disabled {
                color: #8a8a8a;
                border-color: #b5b5b5;
                background: #f0f0f0;
            }
            QLabel {
                font-size: 14px;
            }
            QPlainTextEdit {
                background: #ffffff;
                color: #111111;
                border: 1px solid #222222;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
            }
            """
        )

    def _open_json_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open puzzle JSON", "", "JSON Files (*.json)")
        if path:
            self.load_json_file(Path(path))

    def load_json_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = collect_puzzle_entries_from_json(data)
            if not entries:
                raise ValueError("No compatible puzzle entries were found in the JSON file.")

            for entry in entries:
                if not entry.get("source_file_name"):
                    entry["source_file_name"] = path.name
                if not entry.get("source_file"):
                    entry["source_file"] = str(path)

            self.loaded_entries = entries
            self.loaded_path = path
            self._stop_autofill()
            self.random_button.setEnabled(True)
            self.choose_random_puzzle()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Error", str(exc))

    def choose_random_puzzle(self) -> None:
        if not self.loaded_entries:
            return
        self._stop_autofill()
        self.current_entry = random.choice(self.loaded_entries)
        self.board.set_puzzle(self.current_entry)
        self.board.set_note_mode(False)
        self.note_button.setChecked(False)
        self._update_status()
        self._update_rule_explanation()
        self._update_number_buttons()
        self._update_history_buttons(False, False)
        self._update_interaction_state()

    def _update_status(self) -> None:
        if self.current_entry is None:
            self.status_label.setText("Load a generated JSON file to pick a random puzzle.")
            return
        clue_count = self.current_entry.get("clue_count")
        clue_text = f"clues={clue_count}" if isinstance(clue_count, int) else "clues=unknown"
        source_name = self.current_entry.get("source_file_name") or (
            self.loaded_path.name if self.loaded_path else ""
        )
        rule_name = self.current_entry.get("rule_name") or self.current_entry.get("rule_mode") or "unknown_rule"
        autofill_text = " | auto-filling" if self.autofill_running else ""
        self.status_label.setText(
            f"{source_name} | puzzles={len(self.loaded_entries)} | "
            f"rule={rule_name} | pattern={self.current_entry['pattern_mask']} | {clue_text}{autofill_text}"
        )

    def _update_rule_explanation(self) -> None:
        if self.current_entry is None:
            self.rule_explanation_edit.setPlainText(
                "Load a generated JSON file to see the rule explanation."
            )
            return
        self.rule_explanation_edit.setPlainText(
            build_rule_explanation(
                self.current_entry.get("pattern_mask"),
                self.current_entry.get("rules"),
                rule_name=self.current_entry.get("rule_name") or self.current_entry.get("rule_mode"),
            )
        )

    def _set_note_mode_from_button(self, checked: bool) -> None:
        if self.autofill_running:
            self.note_button.blockSignals(True)
            self.note_button.setChecked(self.board.note_mode)
            self.note_button.blockSignals(False)
            return
        self.board.set_note_mode(checked)
        self.board.setFocus()

    def _sync_note_button(self, enabled: bool) -> None:
        self.note_button.blockSignals(True)
        self.note_button.setChecked(enabled)
        self.note_button.setText("Note: ON" if enabled else "Note: OFF")
        self.note_button.blockSignals(False)

    def _clear_selected_cell(self) -> None:
        if self.autofill_running:
            return
        self.board.clear_selected_cell()
        self.board.setFocus()

    def _input_from_button(self, value: int) -> None:
        if self.autofill_running:
            return
        self.board.input_value(value)
        self.board.setFocus()

    def _undo(self) -> None:
        if self.autofill_running:
            return
        self.board.undo()
        self.board.setFocus()

    def _redo(self) -> None:
        if self.autofill_running:
            return
        self.board.redo()
        self.board.setFocus()

    def _update_history_buttons(self, can_undo: bool, can_redo: bool) -> None:
        self.undo_button.setEnabled(can_undo and not self.autofill_running)
        self.redo_button.setEnabled(can_redo and not self.autofill_running)

    def _update_number_buttons(self) -> None:
        remaining = self.board.remaining_counts()
        for value, button in self.number_buttons.items():
            count = remaining[value]
            if count <= 0:
                button.setText("")
                button.setEnabled(False)
                button.setStyleSheet(
                    "background: transparent; border: 1px solid transparent; color: transparent;"
                )
            else:
                button.setText(f"{value}\n{count} left")
                button.setEnabled(not self.autofill_running)
                button.setStyleSheet("")
        self._update_interaction_state()

    def _set_autofill_enabled(self, enabled: bool) -> None:
        self.autofill_enabled = enabled
        self.autofill_button.setText("Auto-fill <= 9: ON" if enabled else "Auto-fill <= 9: OFF")
        if not enabled:
            self._stop_autofill()
            return
        self._maybe_start_autofill()

    def _maybe_start_autofill(self) -> None:
        if not self.autofill_enabled or self.autofill_running or self.current_entry is None:
            return
        if self.board.remaining_unsolved_count() != 9:
            return
        self.board.begin_autofill_session()
        self.autofill_running = True
        self.board.set_input_locked(True)
        self.autofill_timer.start()
        self._update_interaction_state()
        self._update_status()

    def _run_autofill_step(self) -> None:
        if not self.board.apply_solution_step():
            self._stop_autofill()
            return
        if self.board.remaining_unsolved_count() == 0:
            self._stop_autofill()

    def _stop_autofill(self) -> None:
        self.autofill_timer.stop()
        self.autofill_running = False
        self.board.set_input_locked(False)
        self._update_interaction_state()
        self._update_status()

    def _update_interaction_state(self) -> None:
        self.load_button.setEnabled(not self.autofill_running)
        self.random_button.setEnabled(bool(self.loaded_entries) and not self.autofill_running)
        self.note_button.setEnabled(not self.autofill_running)
        self.clear_button.setEnabled(not self.autofill_running)
        self._update_history_buttons(bool(self.board._undo_stack), bool(self.board._redo_stack))
        for button in self.number_buttons.values():
            if button.text():
                button.setEnabled(not self.autofill_running)

    def _on_puzzle_solved(self) -> None:
        self._stop_autofill()
        QMessageBox.information(self, "Solved", "Puzzle solved.")


def main() -> None:
    app = QApplication(sys.argv)
    json_path = sys.argv[1] if len(sys.argv) >= 2 else None
    window = PlayerWindow(json_path)
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
