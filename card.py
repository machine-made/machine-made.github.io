"""The marks of machine-made: the square logo and the punched card. Standard library only.

The website (build.py), the profile hero and the avatar (brand.py) all draw from this module,
so they match. The logo is a 3 by 3 grid of squares with a red centre. The punched card is a
detail: a card holds one column per character and seven rows, a big dot is a 1 bit, a small dot
is a 0 bit, the top row is the high bit of the 7-bit ASCII code, and one dot is red. A row of
dots on a thin strip is the same code, used as a rule between sections.
"""

import re
from typing import Literal

Mode = Literal["light", "dark"]

MODES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#ffffff",
        "fg": "#000000",
        "muted": "#595959",
        "rule": "#d9d9d9",
        "dot": "#3a3a3a",
        "warp": "#000000",
        "weft": "#bdbdbd",
    },
    "dark": {
        "bg": "#000000",
        "fg": "#ffffff",
        "muted": "#a6a6a6",
        "rule": "#2e2e2e",
        "dot": "#c8c8c8",
        "warp": "#ffffff",
        "weft": "#383838",
    },
}
RED = "#e5251c"

FRAME_W, FRAME_H = 1408, 469
CARD_X, CARD_Y = 512, 64
CARD_H = 341
CUT = 54.56
MARGIN_X, MARGIN_Y = 47.4, 74.05
PITCH_X = (832 - 2 * MARGIN_X) / 37
PITCH_Y = (CARD_H - 2 * MARGIN_Y) / 6
BIG_R = 0.3 * PITCH_X
SMALL = 2.63
ROWS = 7

MARK_SIZE, MARK_CELL, MARK_GAP = 30, 8, 3

RULE_PITCH = 8
RULE_BIG_R = 2.2
RULE_SMALL = 1.2

CAPTION = "The card: the line above in 7-bit ASCII."


def num(value: float) -> str:
    """A number with at most two decimals and no trailing zeros."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def bits(char: str) -> list[int]:
    """The 7 bits of a printable ASCII character, high bit first."""
    code = ord(char)
    if not 32 <= code < 127:
        raise ValueError(f"{char!r} is not printable ASCII")
    return [(code >> shift) & 1 for shift in range(6, -1, -1)]


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def circle(cx: float, cy: float, r: float) -> str:
    return f"M{num(cx - r)} {num(cy)}a{num(r)} {num(r)} 0 1 0 {num(2 * r)} 0a{num(r)} {num(r)} 0 1 0 -{num(2 * r)} 0Z"


def square(cx: float, cy: float, side: float) -> str:
    return f"M{num(cx - side / 2)} {num(cy - side / 2)}h{num(side)}v{num(side)}h-{num(side)}Z"


def card_width(columns: int) -> float:
    return 2 * MARGIN_X + (columns - 1) * PITCH_X


def card_parts(text: str, ox: float, oy: float) -> tuple[str, str, str]:
    """Paths of one card at (ox, oy): the card with its punched holes, the small dots, the red dot.

    The holes are 1 bits and cut through the card (draw it with fill-rule evenodd). The red dot
    sits in the lowest 1 bit of the last column."""
    width = card_width(len(text))
    card = f"M{num(ox + CUT)} {num(oy)}H{num(ox + width)}V{num(oy + CARD_H)}H{num(ox)}V{num(oy + CUT)}Z"
    small, red = "", ""
    for col, char in enumerate(text):
        cx = ox + MARGIN_X + col * PITCH_X
        for row, bit in enumerate(bits(char)):
            cy = oy + MARGIN_Y + row * PITCH_Y
            if bit:
                card += circle(cx, cy, BIG_R)
                if col == len(text) - 1:
                    red = circle(cx, cy, BIG_R)
            else:
                small += square(cx, cy, SMALL)
    return card, small, red


def mark_cells() -> list[tuple[bool, int, int]]:
    """The nine squares of the logo as (is red, x, y) in a 30 by 30 box. The centre is red."""
    step = MARK_CELL + MARK_GAP
    return [((row, col) == (1, 1), col * step, row * step) for row in range(3) for col in range(3)]


def mark_parts(ox: float, oy: float, size: float) -> tuple[str, str]:
    """The logo as paths at (ox, oy), size px wide: the eight dark squares and the red one."""
    k = size / MARK_SIZE
    dark, red = "", ""
    for is_red, x, y in mark_cells():
        box = f"M{num(ox + x * k)} {num(oy + y * k)}h{num(MARK_CELL * k)}v{num(MARK_CELL * k)}h-{num(MARK_CELL * k)}Z"
        if is_red:
            red = box
        else:
            dark += box
    return dark, red


def themed(rules: dict[str, str], red: bool = True) -> str:
    """CSS for an svg that follows the system scheme. rules maps a class to a palette key.
    The red class is left out when the svg has no red."""
    light = "".join(f".{cls}{{fill:{MODES['light'][key]}}}" for cls, key in rules.items())
    dark = "".join(f".{cls}{{fill:{MODES['dark'][key]}}}" for cls, key in rules.items())
    accent = f".r{{fill:{RED}}}" if red else ""
    return f"{light}{accent}@media (prefers-color-scheme:dark){{{dark}}}"


def fixed(mode: Mode, rules: dict[str, str]) -> str:
    """CSS for an svg of one scheme only."""
    return "".join(f".{cls}{{fill:{MODES[mode][key]}}}" for cls, key in rules.items()) + f".r{{fill:{RED}}}"


def svg(width: str, height: str, view: str, title: str, style: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{width}" height="{height}" role="img">\n'
        f"<title>{title}</title>\n<style>{style}</style>\n{body}\n</svg>\n"
    )


def mark_svg() -> str:
    squares = [
        f'<rect class="{"r" if is_red else "k"}" x="{x}" y="{y}" width="{MARK_CELL}" height="{MARK_CELL}"/>'
        for is_red, x, y in mark_cells()
    ]
    size = str(MARK_SIZE)
    return svg(size, size, f"0 0 {size} {size}", "machine-made mark", themed({"k": "fg"}), "\n".join(squares))


def rule_size(text: str) -> tuple[int, int]:
    return (RULE_PITCH * len(text) - 1) * RULE_PITCH, RULE_PITCH


def rule_svg(text: str) -> str:
    """One row of dots that encodes text: 7 slots per character and one empty slot between
    characters. A big dot is a 1 bit, a small dot a 0 bit."""
    path = ""
    for index, char in enumerate(text):
        for slot, bit in enumerate(bits(char)):
            cx = (RULE_PITCH * index + slot + 0.5) * RULE_PITCH
            path += circle(cx, RULE_PITCH / 2, RULE_BIG_R) if bit else square(cx, RULE_PITCH / 2, RULE_SMALL)
    width, height = rule_size(text)
    body = f'<path class="d" d="{path}"/>'
    return svg(str(width), str(height), f"0 0 {width} {height}", f"{text} in 7-bit ASCII", themed({"d": "rule"}, red=False), body)
