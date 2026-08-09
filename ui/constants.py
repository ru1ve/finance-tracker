"""
ui/constants.py — Colour palette and style dictionary.
"""

BG      = "#1e1e2e"
BG2     = "#2a2a3e"
BG3     = "#313149"
FG      = "#cdd6f4"
ACCENT  = "#89b4fa"
GREEN   = "#a6e3a1"
RED     = "#f38ba8"
YELLOW  = "#f9e2af"
MAUVE   = "#cba6f7"
TEAL    = "#94e2d5"
PINK    = "#f5c2e7"
SUBTEXT = "#6c7086"

CAT_COLOURS = {
    "Spending":          RED,
    "Deposit":           ACCENT,
    "Emergency Fund":    YELLOW,
    "Long Term Savings": GREEN,
    "Pension":           MAUVE,
}

STYLE = {
    "bg":        BG,
    "fg":        FG,
    "font":      ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 10, "bold"),
    "font_h1":   ("Segoe UI", 16, "bold"),
    "font_h2":   ("Segoe UI", 12, "bold"),
    "font_mono": ("Consolas", 10),
}
