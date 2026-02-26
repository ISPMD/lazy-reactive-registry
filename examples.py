"""
examples.py
===========
All 7 reactive patterns in one window.
Each tab shows the same ProfileCard made reactive a different way.

Run:  python examples.py
"""

import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from Registry import settings


# ══════════════════════════════════════════════════════════════════════════
# Seed settings
# ══════════════════════════════════════════════════════════════════════════

def seed():
    settings.set("theme.light.bg",     "#ffffff")
    settings.set("theme.light.fg",     "#111111")
    settings.set("theme.light.accent", "#0066cc")
    settings.set("theme.dark.bg",      "#1e1e2e")
    settings.set("theme.dark.fg",      "#cdd6f4")
    settings.set("theme.dark.accent",  "#89b4fa")
    settings.set("theme.mode",         "light")
    settings.set("user.name",          "Alice")
    settings.set("user.role",          "Developer")

seed()

NAMES = ["Alice", "Bob", "Carol", "Dave"]
_name_idx = 0


# ══════════════════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════════════════

def _card_frame() -> tuple[QWidget, QLabel, QLabel]:
    """Return (card widget, name label, role label)."""
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    name = QLabel()
    role = QLabel()
    name.setAlignment(Qt.AlignCenter)
    role.setAlignment(Qt.AlignCenter)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(6)
    lay.addWidget(name)
    lay.addWidget(role)
    return card, name, role


def _apply_style(card, name_lbl, role_lbl):
    bg     = settings.get("theme.bg")
    fg     = settings.get("theme.fg")
    accent = settings.get("theme.accent")
    card.setStyleSheet(
        f"QFrame {{ background: {bg}; border-radius: 10px; border: none; }}"
    )
    name_lbl.setStyleSheet(
        f"color: {accent}; font-size: 20px; font-weight: bold; background: transparent;"
    )
    role_lbl.setStyleSheet(
        f"color: {fg}; font-size: 13px; background: transparent;"
    )
    name_lbl.setText(settings.get("user.name"))
    role_lbl.setText(settings.get("user.role"))


def _wrap(card: QWidget, description: str) -> QWidget:
    """Wrap card + description in a tab page."""
    page = QWidget()
    lay  = QVBoxLayout(page)
    lay.setAlignment(Qt.AlignCenter)

    desc = QLabel(description)
    desc.setWordWrap(True)
    desc.setAlignment(Qt.AlignCenter)
    desc.setStyleSheet("color: #888; font-size: 11px; font-style: italic; padding: 8px;")

    lay.addStretch()
    lay.addWidget(card, alignment=Qt.AlignCenter)
    lay.addWidget(desc)
    lay.addStretch()
    return page


# ══════════════════════════════════════════════════════════════════════════
# Tab 1 — @reactive on an instance method
# ══════════════════════════════════════════════════════════════════════════

class Tab1_ProfileCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)
        self._refresh()

    @settings.reactive
    def _refresh(self):
        _apply_style(self, self._name, self._role)


# ══════════════════════════════════════════════════════════════════════════
# Tab 2 — @reactive on a plain closure
# ══════════════════════════════════════════════════════════════════════════

def make_tab2_card() -> QWidget:
    card, name, role = _card_frame()

    @settings.reactive
    def _refresh():
        _apply_style(card, name, role)

    _refresh()
    card._keep = _refresh   # prevent GC
    return card


# ══════════════════════════════════════════════════════════════════════════
# Tab 3 — composed @reactive methods
# ══════════════════════════════════════════════════════════════════════════

class Tab3_ProfileCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)
        self._refresh()

    @settings.reactive
    def _style(self):
        """Tracks only theme keys."""
        bg     = settings.get("theme.bg")
        fg     = settings.get("theme.fg")
        accent = settings.get("theme.accent")
        self.setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 10px; border: none; }}")
        self._name.setStyleSheet(f"color: {accent}; font-size: 20px; font-weight: bold; background: transparent;")
        self._role.setStyleSheet(f"color: {fg}; font-size: 13px; background: transparent;")

    @settings.reactive
    def _refresh(self):
        """Tracks only content keys."""
        self._name.setText(settings.get("user.name"))
        self._role.setText(settings.get("user.role"))
        self._style()


# ══════════════════════════════════════════════════════════════════════════
# Tab 4 — setting_changed.connect, all keys
# ══════════════════════════════════════════════════════════════════════════

class Tab4_ProfileCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)
        settings.setting_changed.connect(self._on_change)
        self._render()

    def _on_change(self, path, value):
        self._render()

    def _render(self):
        _apply_style(self, self._name, self._role)


# ══════════════════════════════════════════════════════════════════════════
# Tab 5 — setting_changed.connect, filtered
# ══════════════════════════════════════════════════════════════════════════

class Tab5_ProfileCard(QFrame):
    WATCHED = {
        "theme.mode",
        "theme.light.bg", "theme.light.fg", "theme.light.accent",
        "theme.dark.bg",  "theme.dark.fg",  "theme.dark.accent",
        "user.name", "user.role",
    }

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)
        settings.setting_changed.connect(self._on_change)
        self._render()

    def _on_change(self, path, value):
        if path in self.WATCHED:
            self._render()

    def _render(self):
        _apply_style(self, self._name, self._role)


# ══════════════════════════════════════════════════════════════════════════
# Tab 6 — SettingBinding
# ══════════════════════════════════════════════════════════════════════════

class SettingBinding:
    def __init__(self, path, apply):
        self._path  = path
        self._apply = apply
        settings.setting_changed.connect(self._on_change)
        apply(settings.get(path))

    def _on_change(self, path, value):
        if path == self._path:
            self._apply(value)


class Tab6_ProfileCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)

        self._b1 = SettingBinding("user.name", lambda v: self._name.setText(v))
        self._b2 = SettingBinding("user.role", lambda v: self._role.setText(v))

        settings.setting_changed.connect(self._on_theme)
        self._restyle()

    def _on_theme(self, path, value):
        if path.startswith("theme."):
            self._restyle()

    def _restyle(self):
        bg     = settings.get("theme.bg")
        fg     = settings.get("theme.fg")
        accent = settings.get("theme.accent")
        self.setStyleSheet(f"QFrame {{ background: {bg}; border-radius: 10px; border: none; }}")
        self._name.setStyleSheet(f"color: {accent}; font-size: 20px; font-weight: bold; background: transparent;")
        self._role.setStyleSheet(f"color: {fg}; font-size: 13px; background: transparent;")


# ══════════════════════════════════════════════════════════════════════════
# Tab 7 — QTimer polling
# ══════════════════════════════════════════════════════════════════════════

class Tab7_ProfileCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._name = QLabel(); self._name.setAlignment(Qt.AlignCenter)
        self._role = QLabel(); self._role.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addWidget(self._name)
        lay.addWidget(self._role)

        self._last  = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(250)
        self._render()

    def _poll(self):
        snapshot = {
            "mode": settings.get("theme.mode"),
            "name": settings.get("user.name"),
            "role": settings.get("user.role"),
        }
        if snapshot != self._last:
            self._last = snapshot
            self._render()

    def _render(self):
        _apply_style(self, self._name, self._role)


# ══════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SettingsRegistry — Reactive Examples")
        self.setMinimumSize(520, 420)

        root = QWidget()
        self.setCentralWidget(root)
        main_lay = QVBoxLayout(root)
        main_lay.setSpacing(0)
        main_lay.setContentsMargins(16, 16, 16, 16)

        # ── tabs ──────────────────────────────────────────────────────────
        tabs = QTabWidget()
        tabs.addTab(_wrap(Tab1_ProfileCard(),
            "@settings.reactive on an instance method — "
            "re-runs automatically when any key it read changes."),
            "1 · method")

        tabs.addTab(_wrap(make_tab2_card(),
            "@settings.reactive on a plain closure — "
            "use when you don't own the widget class."),
            "2 · closure")

        tabs.addTab(_wrap(Tab3_ProfileCard(),
            "Two @reactive methods: _style() tracks theme keys, "
            "_refresh() tracks content keys — each re-runs independently."),
            "3 · composed")

        tabs.addTab(_wrap(Tab4_ProfileCard(),
            "setting_changed.connect — fires on every key change."),
            "4 · connect all")

        tabs.addTab(_wrap(Tab5_ProfileCard(),
            "setting_changed.connect filtered — "
            "only re-renders when a key in WATCHED changes."),
            "5 · connect filtered")

        tabs.addTab(_wrap(Tab6_ProfileCard(),
            "SettingBinding — one binding maps one key to one setter."),
            "6 · binding")

        tabs.addTab(_wrap(Tab7_ProfileCard(),
            "QTimer polling every 250 ms — "
            "re-renders only when a value actually changed."),
            "7 · polling")

        main_lay.addWidget(tabs)

        # ── controls ──────────────────────────────────────────────────────
        controls = QHBoxLayout()

        btn_theme = QPushButton("Toggle theme")
        btn_theme.clicked.connect(self._toggle_theme)

        btn_name = QPushButton("Cycle name")
        btn_name.clicked.connect(self._cycle_name)

        controls.addWidget(btn_theme)
        controls.addWidget(btn_name)
        main_lay.addLayout(controls)

        self._apply_chrome()
        settings.setting_changed.connect(
            lambda p, v: self._apply_chrome() if p == "theme.mode" else None
        )

    def _toggle_theme(self):
        mode = settings.get("theme.mode")
        settings.set("theme.mode", "dark" if mode == "light" else "light")

    def _cycle_name(self):
        global _name_idx
        _name_idx = (_name_idx + 1) % len(NAMES)
        settings.set("user.name", NAMES[_name_idx])

    def _apply_chrome(self):
        bg = settings.get("theme.bg")
        fg = settings.get("theme.fg")
        ac = settings.get("theme.accent")
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {bg}; color: {fg}; }}
            QTabWidget::pane     {{ border: 1px solid {fg}22; border-radius: 6px; }}
            QTabBar::tab         {{ background: {bg}; color: {fg}; padding: 6px 14px;
                                   border: 1px solid {fg}22; border-bottom: none;
                                   border-top-left-radius: 4px; border-top-right-radius: 4px; }}
            QTabBar::tab:selected {{ border-bottom: 2px solid {ac}; color: {ac}; }}
            QPushButton          {{ background: {bg}; color: {fg}; padding: 6px 18px;
                                   border: 1px solid {fg}44; border-radius: 4px; }}
            QPushButton:hover    {{ border-color: {ac}; color: {ac}; }}
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
