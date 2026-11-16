"""Charte graphique : bleu foncé, blanc, gris clair."""

NAVY = "#0F2A4A"
NAVY_2 = "#16365C"
ACCENT = "#2F6FB3"
LIGHT = "#F3F5F8"
GREY = "#D9DEE5"
TEXT = "#1E2633"
MUTED = "#5F6B7A"
SUCCESS = "#2E8B57"
WARNING = "#C98A0B"
DANGER = "#C0392B"

STYLESHEET = f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 10.5pt; color: {TEXT}; }}
QMainWindow, QWidget#Content {{ background: {LIGHT}; }}
QWidget#Sidebar {{ background: {NAVY}; }}
QLabel#Brand {{ color: white; font-size: 13pt; font-weight: 700; padding: 18px 16px 2px 16px; }}
QLabel#BrandSub {{ color: #9FB6D3; font-size: 9pt; padding: 0 16px 14px 16px; }}
QListWidget#Nav {{ background: transparent; border: none; outline: 0; }}
QListWidget#Nav::item {{ color: #D5E1F0; padding: 9px 14px; border-left: 3px solid transparent; }}
QListWidget#Nav::item:hover {{ background: {NAVY_2}; }}
QListWidget#Nav::item:selected {{ background: {NAVY_2}; color: white; border-left: 3px solid #6FA8E8; }}
QLabel#PageTitle {{ font-size: 18pt; font-weight: 700; color: {NAVY}; }}
QLabel#PageSubtitle {{ color: {MUTED}; }}
QLabel#H2 {{ font-size: 12.5pt; font-weight: 600; color: {NAVY}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Disclaimer {{ color: {MUTED}; font-size: 9pt; font-style: italic; }}
QFrame#Card {{ background: white; border: 1px solid {GREY}; border-radius: 10px; }}
QLabel#KpiValue {{ font-size: 20pt; font-weight: 700; color: {NAVY}; }}
QLabel#KpiLabel {{ color: {MUTED}; font-size: 9pt; }}
QPushButton {{ background: white; border: 1px solid {GREY}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #9AA3AE; background: #EEF0F3; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #255D98; }}
QPushButton#Choice {{ text-align: left; padding: 10px 14px; }}
QPushButton#Choice:checked {{ background: #E3EEFA; border: 2px solid {ACCENT}; }}
QPushButton#ChoiceRight {{ text-align: left; padding: 10px 14px; background: #E5F4EC; border: 2px solid {SUCCESS}; }}
QPushButton#ChoiceWrong {{ text-align: left; padding: 10px 14px; background: #FBE9E7; border: 2px solid {DANGER}; }}
QLabel#Timer {{ font-size: 15pt; font-weight: 700; color: {NAVY}; background: white;
               border: 1px solid {GREY}; border-radius: 8px; padding: 4px 12px; }}
QLabel#TimerLow {{ font-size: 15pt; font-weight: 700; color: white; background: {DANGER};
                  border-radius: 8px; padding: 4px 12px; }}
QTextEdit, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {{ background: white; border: 1px solid {GREY};
    border-radius: 6px; padding: 6px; }}
QTextBrowser {{ background: white; border: 1px solid {GREY}; border-radius: 8px; padding: 10px; }}
QTableWidget {{ background: white; border: 1px solid {GREY}; gridline-color: {GREY}; }}
QHeaderView::section {{ background: {LIGHT}; border: none; border-bottom: 1px solid {GREY}; padding: 6px; font-weight: 600; }}
QProgressBar {{ border: 1px solid {GREY}; border-radius: 5px; background: white; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QTabWidget::pane {{ border: 1px solid {GREY}; background: white; border-radius: 6px; }}
QTabBar::tab {{ padding: 7px 14px; }}
QTabBar::tab:selected {{ color: {ACCENT}; font-weight: 600; }}
QScrollArea {{ border: none; background: transparent; }}
QListWidget#Filters {{ background: white; border: 1px solid {GREY}; border-radius: 8px; outline: 0; }}
QListWidget#Filters::item {{ padding: 9px 12px; border-left: 3px solid transparent; }}
QListWidget#Filters::item:selected {{ background: #E3EEFA; color: {NAVY}; border-left: 3px solid {ACCENT}; }}
QLabel#H3 {{ font-weight: 600; color: {NAVY}; padding-top: 6px; }}
QRadioButton {{ padding: 4px 2px; }}
"""
