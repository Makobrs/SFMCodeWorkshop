"""Visual tokens and Qt stylesheet for SFM Code Workshop.

The visual language follows the approved endfield-workbench design:
paper/ink, one amber signal, cut corners only on pressable things,
1px rules, no rounded cards, no shadows/glows, red only for delete.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ..core.storage import resource_root


@dataclass(frozen=True)
class Theme:
    name: str
    paper: str
    panel: str
    ink: str
    ink2: str
    rule: str
    chip: str
    signal: str
    on_signal: str
    trace: str
    danger: str
    danger_bg: str
    grid: str
    command: str
    command_ink: str
    command_muted: str
    command_rule: str
    surface2: str = "#ECE8DC"
    signal_soft: str = "#F2DCA8"
    ok: str = "#3D6B55"
    ok_bg: str = "#E4EEE7"
    warn_bg: str = "#F6EBD0"
    haze: str = "#B9B4A7"
    spotlight: str = "#FFF7DE"

    @property
    def dark(self) -> bool:
        return self.name == "dark"


LIGHT = Theme(
    name="light",
    paper="#F3F1EA",
    panel="#FFFEFA",
    ink="#161616",
    ink2="#5C5C5C",
    rule="#DCD8CC",
    chip="#E7E3D8",
    signal="#FFB31F",
    on_signal="#161616",
    trace="#161616",
    danger="#B3261E",
    danger_bg="#F6E3E0",
    grid="#DDD9CF",
    command="#161616",
    command_ink="#F3F1EA",
    command_muted="#9B9B9B",
    command_rule="#38352F",
    surface2="#ECE8DC",
    signal_soft="#F2DCA8",
    ok="#3D6B55",
    ok_bg="#E4EEE7",
    warn_bg="#F6EBD0",
    haze="#B9B4A7",
    spotlight="#FFF7DE",
)

DARK = Theme(
    name="dark",
    paper="#1B1A17",
    panel="#24221E",
    ink="#EDEDED",
    ink2="#B8B1A4",
    rule="#5E5749",
    chip="#3A352D",
    signal="#FFB31F",
    on_signal="#161616",
    trace="#FFB31F",
    danger="#FF8A7A",
    danger_bg="#3A2422",
    grid="#454037",
    command="#161616",
    command_ink="#F3F1EA",
    command_muted="#9B9B9B",
    command_rule="#38352F",
    surface2="#2C2F2E",
    signal_soft="#5B4925",
    ok="#83B79B",
    ok_bg="#20332A",
    warn_bg="#352D1F",
    haze="#777C78",
    spotlight="#362D1B",
)

THEMES = {"light": LIGHT, "dark": DARK}

_FONT_LOADED = False


def _font_path() -> Path:
    from ..core.storage import resource_root

    return resource_root() / "fonts" / "Saira.ttf"


def ensure_fonts() -> None:
    global _FONT_LOADED
    if _FONT_LOADED:
        return
    p = _font_path()
    if p.exists():
        QFontDatabase.addApplicationFont(str(p))
    _FONT_LOADED = True


def ui_font(size: int = 11, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    ensure_fonts()
    # Keep 8px metadata readable at 100% Windows scaling.  Layout width is
    # handled responsively in MainWindow/OverviewPage instead of shrinking type.
    size = max(10, int(size))
    f = QFont()
    f.setFamilies(["Saira", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def mono_font(size: int = 11) -> QFont:
    ensure_fonts()
    size = max(10, int(size))
    f = QFont()
    f.setFamilies(["Cascadia Mono", "Consolas", "Saira", "Microsoft YaHei UI"])
    f.setPixelSize(size)
    return f


def qss(t: Theme) -> str:
    arrow = (resource_root() / "icons" / ("chevron-down-dark.svg" if t.dark else "chevron-down-light.svg")).as_posix()
    return f"""
    * {{
        outline: none;
    }}
    QWidget {{
        background: {t.paper};
        color: {t.ink};
        font-family: "Saira", "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    }}
    QMainWindow, QDialog {{
        background: {t.paper};
    }}
    QWidget#Root, QWidget#Page {{
        background: {t.paper};
    }}
    QWidget#CommandBar {{
        background: {t.command};
        color: {t.command_ink};
    }}
    QFrame#Panel {{
        background: {t.panel};
        border: 1px solid {t.rule};
    }}
    QFrame#FlatPanel {{
        background: transparent;
        border: 0;
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel#Eyebrow {{
        color: {t.ink2};
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#Muted {{
        color: {t.ink2};
    }}
    QLabel#Signal {{
        color: {t.on_signal};
        background: {t.signal};
        padding: 1px 5px;
        font-weight: 800;
        font-size: 11px;
    }}
    QLabel#Danger {{
        color: {t.danger};
    }}
    QLabel#Ink {{
        color: {t.ink};
    }}
    QLabel#BrandMark {{
        background: {t.signal};
        color: {t.on_signal};
        font-weight: 900;
        font-size: 17px;
    }}
    QFrame#CommandRow {{
        background: {t.panel};
        border: 1px solid {t.rule};
    }}
    QLabel#CommandText {{
        color: {t.ink};
        font-family: "Cascadia Mono", "Consolas", "Saira", "Microsoft YaHei UI";
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#CommandChip {{
        background: {t.panel};
        color: {t.ink};
        border: 1px solid {t.rule};
        padding: 5px 9px;
        font-family: "Cascadia Mono", "Consolas", "Saira", "Microsoft YaHei UI";
        font-size: 11px;
        font-weight: 700;
        text-align: left;
    }}
    QPushButton#CommandChip:hover {{
        border-color: {t.ink};
        background: {t.chip};
    }}
    QPushButton#SidebarNav {{
        background: transparent;
        color: {t.ink};
        border: 0;
        text-align: left;
        padding: 7px 9px;
        font-size: 11px;
    }}
    QPushButton#SidebarNav:hover {{
        background: {t.chip};
    }}
    QPushButton#SidebarPlus {{
        background: transparent;
        color: {t.ink2};
        border: 1px solid {t.rule};
        padding: 0;
        font-size: 13px;
    }}
    QPushButton#SidebarPlus:hover {{
        color: {t.ink};
        border-color: {t.ink};
    }}
    QLabel#WorkspaceGroup {{
        color: {t.ink2};
        background: transparent;
        padding: 8px 5px 3px 5px;
        border-bottom: 1px solid {t.rule};
    }}
    QFrame#WorkspaceRow {{
        background: transparent;
        border: 0;
    }}
    QFrame#WorkspaceRow:hover {{
        background: {t.chip};
    }}
    QLabel#WorkspaceArrow {{
        color: {t.ink2};
        background: transparent;
    }}
    QLabel#WorkspaceName {{
        color: {t.ink};
        background: transparent;
    }}
    QLabel#WorkspaceName[active="true"] {{
        color: {t.ink};
    }}
    QPushButton#WorkspaceAction {{
        background: transparent;
        border: 0;
        padding: 0;
        color: {t.ink2};
    }}
    QPushButton#WorkspaceAction:hover {{
        background: {t.rule};
    }}
    QFrame#SessionRow {{
        background: transparent;
        border: 0;
        border-left: 2px solid transparent;
    }}
    QFrame#SessionRow:hover {{
        background: {t.chip};
    }}
    QFrame#SessionRow[current="true"] {{
        background: {t.chip};
        border-left: 2px solid {t.trace};
    }}
    QLabel#SessionTitle {{
        color: {t.ink};
        background: transparent;
    }}
    QLabel#SessionTime {{
        color: {t.ink2};
        background: transparent;
    }}
    QLabel#SessionTime[current="true"] {{
        color: {t.ink};
    }}
    QPushButton#FaceOption {{
        background: {t.panel};
        color: {t.ink};
        border: 1px solid {t.rule};
        text-align: left;
        padding: 6px 9px;
        font-size: 11px;
    }}
    QPushButton#FaceOption:hover {{
        background: {t.chip};
        border-color: {t.ink};
    }}
    QPushButton#FaceOption[current="true"] {{
        border: 2px solid {t.signal};
    }}
    QLineEdit#SidebarSearch {{
        background: {t.panel};
        border: 1px solid {t.rule};
        padding: 4px 6px;
        font-size: 11px;
    }}
    QFrame#RecentRow {{
        background: transparent;
        border: 0;
        border-left: 2px solid transparent;
    }}
    QFrame#RecentRow:hover {{
        background: {t.chip};
    }}
    QFrame#RecentRow[current="true"] {{
        background: {t.panel};
        border-left: 2px solid {t.signal};
    }}
    QFrame#SidebarStatus {{
        background: {t.panel};
        border-top: 1px solid {t.rule};
    }}
    QPushButton#SidebarRecycle {{
        background: transparent;
        border: 0;
        color: {t.ink2};
        text-align: left;
        padding: 4px 0;
        font-size: 11px;
    }}
    QPushButton#SidebarRecycle:hover {{
        color: {t.ink};
    }}
    QWidget#SidebarContent, QScrollArea#SidebarScroll {{
        background: {t.paper};
    }}
    QFrame#ProjectBar {{
        background: {t.paper};
        border-bottom: 1px solid {t.rule};
    }}
    QLineEdit#ProjectName {{
        background: transparent;
        border: 0;
        padding: 0;
        font-weight: 700;
    }}
    QLineEdit#ProjectName:focus {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {t.signal};
    }}
    QLabel#ProjectEditHint {{
        background: transparent;
    }}
    QFrame#TemplateRow {{
        background: {t.panel};
        border: 1px solid {t.rule};
        border-left: 2px solid transparent;
    }}
    QFrame#TemplateRow:hover, QFrame#TemplateRow:focus {{
        background: {t.chip};
        border-color: {t.ink2};
        border-left-color: {t.ink2};
    }}
    QFrame#TemplateRow[selected="true"] {{
        background: {t.chip};
        border-color: {t.ink};
        border-left: 2px solid {t.signal};
    }}
    QFrame#TemplateEmpty {{
        background: transparent;
        border: 1px dashed {t.rule};
    }}
    QFrame#AIStatus {{
        background: {t.panel};
        border: 1px solid {t.rule};
        border-left: 3px solid {t.rule};
    }}
    QFrame#AIStatus[state="running"], QFrame#AIStatus[state="review"] {{
        border-left-color: {t.signal};
    }}
    QFrame#AIStatus[state="done"] {{
        border-left-color: {t.ink};
    }}
    QFrame#AIStatus[state="warning"], QFrame#AIStatus[state="error"] {{
        border-left-color: {t.signal};
    }}
    QLabel#AIStatusTitle {{
        color: {t.ink};
        font-size: 11px;
        font-weight: 700;
    }}
    QFrame#InlineStatus {{
        background: {t.panel};
        border: 1px solid {t.rule};
        border-left: 3px solid {t.ink2};
    }}
    QFrame#InlineStatus[level="block"], QFrame#InlineStatus[level="possible"] {{
        background: rgba(255, 179, 31, 18);
        border: 1px solid {t.ink};
        border-left: 3px solid {t.signal};
    }}
    QLabel#InlineTitle {{
        color: {t.ink};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#InlineDetail {{
        color: {t.ink2};
        font-size: 11px;
    }}
    QWidget#IssueRow {{
        border: 0;
        border-left: 2px solid transparent;
    }}
    QWidget#IssueRow:hover {{
        background: {t.chip};
        border-left-color: {t.signal};
    }}
    QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
        background: {t.panel};
        color: {t.ink};
        border: 1px solid {t.rule};
        border-radius: 0;
        padding: 4px 7px;
        selection-background-color: {t.signal};
        selection-color: {t.on_signal};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {t.ink};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
        color: {t.ink2};
        background: {t.chip};
    }}
    QComboBox::drop-down {{
        border: 0;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: url("{arrow}");
        width: 11px;
        height: 11px;
    }}
    QComboBox QAbstractItemView {{
        background: {t.panel};
        color: {t.ink};
        border: 1px solid {t.ink};
        selection-background-color: {t.chip};
        selection-color: {t.ink};
        outline: 0;
    }}
    QComboBox#CommandCombo {{
        background: transparent;
        color: {t.command_ink};
        border: 1px solid {t.command_rule};
        padding: 3px 7px;
    }}
    QComboBox#CommandCombo:hover {{
        border-color: {t.command_ink};
    }}
    QComboBox#CommandCombo QAbstractItemView {{
        background: {t.command};
        color: {t.command_ink};
        border: 1px solid {t.command_rule};
        selection-background-color: {t.chip};
        selection-color: {t.ink};
    }}
    QPushButton {{
        background: transparent;
        color: {t.ink};
        border: 1px solid {t.rule};
        border-radius: 0;
        padding: 5px 10px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        border-color: {t.ink};
        background: {t.chip};
    }}
    QPushButton:pressed {{
        background: {t.signal};
        color: {t.on_signal};
    }}
    QPushButton:disabled {{
        color: {t.ink2};
        border-color: {t.rule};
        background: transparent;
    }}
    QPushButton#Danger {{
        color: {t.danger};
        border-color: {t.danger};
    }}
    QPushButton#Danger:hover {{
        background: {t.danger_bg};
    }}
    QCheckBox {{
        spacing: 6px;
        color: {t.ink};
    }}
    QCheckBox::indicator {{
        width: 13px;
        height: 13px;
        border: 1px solid {t.ink2};
        background: {t.panel};
    }}
    QCheckBox::indicator:checked {{
        background: {t.signal};
        border-color: {t.ink};
    }}
    QScrollArea {{
        border: 0;
        background: {t.paper};
    }}
    QScrollArea > QWidget > QWidget {{
        background: {t.paper};
    }}
    QScrollBar:vertical {{
        background: {t.paper};
        width: 9px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t.haze};
        min-height: 24px;
        border-radius: 0;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t.ink2};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: {t.paper};
        height: 9px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t.haze};
        min-width: 24px;
        border-radius: 0;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QToolTip {{
        background: {t.command};
        color: {t.command_ink};
        border: 1px solid {t.command_rule};
        padding: 4px 6px;
    }}
    QListWidget {{
        background: transparent;
        border: 0;
        outline: 0;
    }}
    QListWidget::item {{
        background: transparent;
        border: 0;
        padding: 0;
    }}
    QListWidget::item:selected {{
        background: {t.chip};
        color: {t.ink};
    }}
    QSplitter::handle {{
        background: {t.rule};
        width: 1px;
        height: 1px;
    }}
    QTabWidget::pane {{
        border: 1px solid {t.rule};
        background: {t.panel};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t.ink2};
        border: 0;
        padding: 6px 12px;
    }}
    QTabBar::tab:selected {{
        color: {t.ink};
        border-bottom: 2px solid {t.trace};
    }}
    QMenu {{
        background: {t.panel};
        color: {t.ink};
        border: 1px solid {t.ink};
    }}
    QMenu::item {{
        padding: 6px 22px;
    }}
    QMenu::item:selected {{
        background: {t.chip};
    }}
    QFrame#HLine {{
        background: {t.rule};
        max-height: 1px;
        border: 0;
    }}
    QPushButton#Tab {{
        background: transparent;
        border: 0;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        color: {t.ink2};
        padding: 5px 0 6px 0;
        margin-right: 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QPushButton#Tab:hover {{
        color: {t.ink};
        background: transparent;
        border-bottom-color: {t.rule};
    }}
    QPushButton#Tab:checked {{
        color: {t.ink};
        border-bottom-color: {t.trace};
        background: transparent;
    }}
    QPushButton#Tab:focus {{
        border: 1px dotted {t.ink2};
        border-bottom-color: {t.trace};
    }}
    QFrame#QuickTile:focus {{
        border: 1px dotted {t.ink2};
        border-left: 2px solid {t.signal};
    }}
    QFrame#CommandHLine {{
        background: {t.command_rule};
        max-height: 1px;
        border: 0;
    }}
    QLabel#CommandBrand {{
        color: {t.command_ink};
        font-size: 13px;
        font-weight: 800;
    }}
    QLabel#CommandMuted {{
        color: {t.command_muted};
    }}
    QLabel#CommandProject {{
        color: {t.command_ink};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#Status {{
        color: {t.ink2};
        font-size: 11px;
    }}
    QLabel#Code {{
        color: {t.ink};
        font-family: "Cascadia Mono", "Consolas", "Saira", "Microsoft YaHei UI";
        font-size: 11px;
    }}
    QPlainTextEdit#CodeView {{
        background: {t.panel};
        color: {t.ink};
        border: 0;
        padding: 8px 10px;
        font-family: "Cascadia Mono", "Consolas", "Saira", "Microsoft YaHei UI";
        font-size: 11px;
    }}
    QLabel#EmptyTitle {{
        color: {t.ink};
        font-size: 14px;
        font-weight: 700;
    }}
    QLabel#EmptyBody {{
        color: {t.ink2};
        font-size: 11px;
    }}
    /* ---- v0.2 overview / inspector / command surface ---- */
    QWidget#OverviewBody, QScrollArea#OverviewScroll {{
        background: {t.paper};
        border: 0;
    }}
    QFrame#HeroPanel {{
        background: {t.panel};
        border: 1px solid {t.rule};
        border-left: 3px solid {t.signal};
    }}
    QLabel#HeroTitle {{
        color: {t.ink};
        font-size: 28px;
        font-weight: 800;
    }}
    QLabel#HeroSub {{
        color: {t.ink2};
        font-size: 11px;
    }}
    QLabel#HeroStatus {{
        color: {t.ink2};
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
        padding: 2px 0;
    }}
    QLabel#HeroStatus[dirty="true"] {{
        color: {t.signal};
    }}
    QFrame#StatCard {{
        background: {t.panel};
        border: 1px solid {t.rule};
        border-top: 2px solid {t.ink2};
    }}
    QFrame#StatCard[accent="true"] {{
        border-top-color: {t.signal};
        background: {t.chip};
    }}
    QFrame#StatCard:hover {{
        background: {t.chip};
        border-color: {t.ink2};
        border-top-color: {t.signal};
    }}
    QFrame#StatCard:focus {{
        border: 1px dotted {t.ink2};
        border-top: 2px solid {t.signal};
    }}
    QFrame#StatCard[tone="bad"] {{
        border-top-color: {t.danger};
    }}
    QFrame#StatCard[tone="warn"] {{
        border-top-color: {t.signal};
    }}
    QFrame#StatCard[tone="ok"] {{
        border-top-color: {t.ok};
    }}
    QLabel#StatLabel {{
        color: {t.ink2};
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#StatValue {{
        color: {t.ink};
        font-size: 23px;
        font-weight: 800;
    }}
    QLabel#StatHint {{
        color: {t.ink2};
        font-size: 11px;
    }}
    QFrame#QuickTile {{
        background: transparent;
        border: 1px solid transparent;
        border-left: 1px solid {t.rule};
    }}
    QFrame#QuickTile:hover {{
        background: {t.chip};
        border-color: {t.rule};
        border-left-color: {t.signal};
    }}
    QFrame#QuickTile:pressed {{
        background: {t.surface2};
    }}
    QLabel#QuickHint {{
        color: {t.ink2};
        font-size: 11px;
    }}
    QLabel#QuickArrow {{
        color: {t.ink2};
        font-size: 12px;
    }}
    QFrame#HealthPanel, QFrame#EnvironmentCard, QFrame#ActivityFeed, QFrame#OverviewPanel {{
        background: {t.panel};
        border: 1px solid {t.rule};
    }}
    QFrame#HealthSegment {{
        background: {t.rule};
        border: 0;
    }}
    QFrame#HealthSegment[ok="true"] {{
        background: {t.signal};
    }}
    QLabel#MiniBadge {{
        background: {t.chip};
        color: {t.ink2};
        border: 1px solid {t.rule};
        padding: 2px 5px;
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
    }}
    QLabel#MiniBadge[tone="ok"] {{
        color: {t.ok};
        border-color: {t.ok};
        background: {t.ok_bg};
    }}
    QLabel#MiniBadge[tone="warn"] {{
        color: {t.ink};
        border-color: {t.signal};
        background: {t.warn_bg};
    }}
    QLabel#MiniBadge[tone="bad"] {{
        color: {t.danger};
        border-color: {t.danger};
        background: {t.danger_bg};
    }}
    QLabel#MiniBadge[tone="idle"] {{
        color: {t.ink2};
        border-color: {t.rule};
        background: transparent;
    }}
    QLabel#MonoMuted {{
        color: {t.ink2};
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
    }}
    QLabel#Muted {{
        color: {t.ink2};
    }}
    QFrame#ActivityRow {{
        border: 0;
        background: transparent;
    }}
    QLabel#ActivityNum {{
        color: {t.signal};
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
        min-width: 18px;
    }}
    QLabel#ActivityKind {{
        color: {t.ink2};
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
    }}
    QFrame#Inspector {{
        background: {t.panel};
        border: 0;
        border-left: 1px solid {t.rule};
    }}
    QLabel#InspectorTitle {{
        color: {t.ink};
        font-size: 15px;
        font-weight: 700;
    }}
    QFrame#InspectRow {{
        border: 0;
        border-bottom: 1px solid {t.rule};
        background: transparent;
    }}
    QLabel#InspectValue {{
        color: {t.ink};
        font-size: 11px;
    }}
    QWidget#RulesPage {{
        background: {t.paper};
    }}
    QDialog#CommandPalette {{
        background: {t.panel};
        border: 1px solid {t.ink2};
    }}
    QFrame#PaletteHead {{
        background: {t.command};
        border: 0;
        border-bottom: 1px solid {t.command_rule};
    }}
    QLineEdit#PaletteSearch {{
        background: transparent;
        color: {t.command_ink};
        border: 0;
        padding: 5px 0;
        font-size: 14px;
    }}
    QLineEdit#PaletteSearch::placeholder {{
        color: {t.command_muted};
    }}
    QListWidget#PaletteList {{
        background: {t.panel};
        color: {t.ink};
        border: 0;
        padding: 5px;
        outline: none;
    }}
    QListWidget#PaletteList::item {{
        min-height: 30px;
        padding: 4px 8px;
        border-left: 2px solid transparent;
    }}
    QListWidget#PaletteList::item:selected {{
        background: {t.chip};
        border-left-color: {t.signal};
        color: {t.ink};
    }}
    QFrame#PaletteFoot {{
        background: {t.paper};
        border-top: 1px solid {t.rule};
    }}
    QLabel#Kbd {{
        background: {t.chip};
        color: {t.ink2};
        border: 1px solid {t.rule};
        padding: 1px 4px;
        font-family: "Cascadia Mono", "Consolas";
        font-size: 11px;
    }}
    """


_current = LIGHT


def apply_theme(app: QApplication, theme: Theme) -> None:
    global _current
    _current = theme
    app.setFont(ui_font(12))
    app.setStyleSheet(qss(theme))


def current() -> Theme:
    return _current

