"""Window-local visual styling; native widgets retain their keyboard behavior."""

STYLE = """
QWidget#navigationRail { background: #142b40; border-radius: 8px; }
QLabel#brand { color: #f1f6fa; font-size: 21px; font-weight: bold; padding: 14px 8px 0; }
QLabel#brandCaption { color: #acbdcc; padding: 0 8px 20px; }
QListWidget#navigation { background: transparent; border: none; color: #c9d6e0; outline: none; }
QListWidget#navigation::item { padding: 12px 8px; border: 1px solid transparent; border-radius: 5px; }
QListWidget#navigation::item:selected { background: #2a4b65; color: white; border-color: #496c87; }
QListWidget#navigation::item:hover { background: #213d54; }
QListWidget#navigation::item:focus { border-color: #a8d6f3; }
QLabel#pageTitle { font-size: 25px; font-weight: bold; padding-top: 4px; }
QLabel#pageDescription, QLabel#settingDescription, QLabel#readback { color: palette(text); }
QLabel#deviceTitle { padding: 6px 0; }
QLabel#feedback { padding: 8px; background: palette(alternate-base); border-radius: 4px; }
QWidget#actionShelf { border-top: 1px solid palette(mid); }
QGroupBox { border: 1px solid palette(mid); border-radius: 6px; margin-top: 16px; padding: 16px 12px 12px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 5px; }
QPushButton { min-height: 24px; padding: 4px 10px; }
QPushButton#applyAction:enabled { background: #195b83; color: white; border: 1px solid #195b83; border-radius: 4px; }
QPushButton#applyAction:hover:enabled { background: #104565; }
QPushButton#stopAction:enabled { color: #a13232; background: #fff5f3; border: 1px solid #c99090; border-radius: 4px; }
QPushButton:focus { border: 2px solid palette(highlight); }
QPushButton#applyAction:enabled:focus, QPushButton#stopAction:enabled:focus { border: 2px solid palette(highlight); }
QLineEdit, QComboBox, QAbstractSpinBox { min-height: 26px; padding: 3px 6px; }
QTabWidget::pane { border: 1px solid palette(mid); border-radius: 4px; }
QTabBar::tab { padding: 9px 12px; }
QTreeView, QPlainTextEdit, QListWidget { border: 1px solid palette(mid); border-radius: 4px; }
QTreeView::item { padding: 6px 3px; }
QHeaderView::section { padding: 7px; }
QProgressBar { min-height: 18px; border: 1px solid palette(mid); border-radius: 3px; text-align: center; }
QProgressBar::chunk { background: palette(highlight); border-radius: 2px; }
"""
