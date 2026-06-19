"""UI colour tags and theme palettes (pure constants, no I/O)."""

from __future__ import annotations

TAG_BLACK = "black"
TAG_BLUE = "blue"
TAG_GREEN = "green"
TAG_GREY = "grey"
TAG_ORANGE = "orange"
TAG_RED = "red"

THEME_DEFAULT = "default"
THEME_DARK = "dark"
THEME_LIGHT = "light"

theme_config: dict[str, dict[str, str]] = {
    THEME_DARK: {
        TAG_BLACK: "light grey",
        TAG_BLUE: "#7289DA",
        TAG_GREEN: "#4E9D4E",
        TAG_GREY: "grey",
        TAG_ORANGE: "#FF981F",
        TAG_RED: "#F04747",
        "background": "#36393E",
        "muted": "#B8BCC4",
        "surface": "#2F3136",
        "text_background": "#26282D",
    },
    THEME_LIGHT: {
        TAG_BLACK: "black",
        TAG_BLUE: "blue",
        TAG_GREEN: "green",
        TAG_GREY: "grey",
        TAG_ORANGE: "orange",
        TAG_RED: "red",
        "background": "white",
        "muted": "#5E6878",
        "surface": "#F4F7FB",
        "text_background": "#FBFCFE",
    },
}
