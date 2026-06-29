"""VAICOM vocabulary generator packaged with VAIVOX (ADR-0005).

This module intentionally mirrors the historical ``tools/generate_vaicom_keyterms.py``
script, but lives under ``src/vaivox`` so PyInstaller bundles it with the application.
The command-line script remains as a thin wrapper for maintainers.
"""

# ruff: noqa: B033, D103, E501

from __future__ import annotations

import argparse
import html
import json
import os
import re
import unicodedata
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path

from vaivox.infrastructure.vocabulary.command_catalog import (
    COMMAND_CATALOG_FILE,
    COMMAND_CATALOG_VERSION,
    CommandCatalogEntry,
)

DEFAULT_DCS_SAVED_GAMES = Path.home() / "Saved Games" / "DCS"
DEFAULT_MAX_KEYTERMS = 850
DEFAULT_MAX_PHRASES = 2000

# Output file names the app loaders read from the per-user VAIVOX data dir (ADR-0005):
# vaivox.infrastructure.vocabulary.vaicom_keyterms / .phrase_index.
KEYTERMS_FILE = "vaicom_keyterms.txt"
PHRASE_INDEX_FILE = "phrase_index.txt"


def default_data_dir() -> Path:
    """Return the per-user VAIVOX data directory the app loaders read (ADR-0005)."""
    base = os.getenv("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "VAIVOX"


TECHNICAL_WORDS = {
    "AAA",
    "ADF",
    "APX",
    "ATC",
    "AVTR",
    "AWACS",
    "BATH",
    "BDA",
    "CMS",
    "DCS",
    "ECM",
    "FARP",
    "GBU",
    "GCA",
    "HMD",
    "IFF",
    "IFR",
    "ILS",
    "INS",
    "JTAC",
    "LAV",
    "LSO",
    "NVG",
    "PAR",
    "RIO",
    "RTB",
    "RWS",
    "SAM",
    "STT",
    "TACAN",
    "TV",
    "TWS",
    "VFR",
    "VHF",
    "VSL",
    "UHF",
    "WSO",
}

HIGH_PRIORITY_PROPER_WORDS = {
    "Arco",
    "Darkstar",
    "Enfield",
    "Focus",
    "Magic",
    "Overlord",
    "Shell",
    "Texaco",
    "Wizard",
    "George",
    "Gunner",
    "Jester",
}

HIGH_PRIORITY_COMMAND_WORDS = {
    "abort",
    "active",
    "alignment",
    "approach",
    "arm",
    "attack",
    "beacon",
    "bogey",
    "bogeys",
    "boresight",
    "break",
    "breakaway",
    "bullseye",
    "canopy",
    "carrier",
    "chaff",
    "channel",
    "chocks",
    "clearance",
    "cleared",
    "climb",
    "cold",
    "contact",
    "copy",
    "countermeasures",
    "crew",
    "damage",
    "departure",
    "designate",
    "disconnect",
    "divert",
    "eject",
    "emergency",
    "engage",
    "engine",
    "engines",
    "established",
    "flare",
    "flares",
    "fuel",
    "guns",
    "heading",
    "hot",
    "hover",
    "inbound",
    "interrogate",
    "jammer",
    "jettison",
    "landing",
    "laser",
    "launch",
    "lock",
    "meatball",
    "missile",
    "missiles",
    "monitor",
    "picture",
    "precontact",
    "radar",
    "radio",
    "refuel",
    "refueling",
    "repair",
    "report",
    "runway",
    "shutdown",
    "smoke",
    "spike",
    "startup",
    "status",
    "steerpoint",
    "stores",
    "tacan",
    "takeoff",
    "tally",
    "tanker",
    "target",
    "targets",
    "taxi",
    "tower",
    "traffic",
    "tune",
    "vector",
    "vectors",
    "visual",
    "waypoint",
    "weapon",
    "weapons",
    "wheelchocks",
}

COMMON_WORDS = {
    "abort",
    "absolute",
    "active",
    "activity",
    "air",
    "airborne",
    "airfield",
    "aft",
    "airfields",
    "alignment",
    "altitude",
    "approach",
    "approaching",
    "area",
    "arm",
    "armor",
    "astern",
    "attack",
    "auto",
    "automatic",
    "away",
    "base",
    "asset",
    "astern",
    "aug",
    "beacon",
    "beam",
    "big",
    "bogey",
    "bogeys",
    "bomb",
    "bombs",
    "boresight",
    "break",
    "breakaway",
    "briefing",
    "bullseye",
    "canopy",
    "carrier",
    "cartridges",
    "center",
    "centre",
    "chaff",
    "channel",
    "check",
    "checking",
    "chocks",
    "city",
    "clear",
    "clearance",
    "cleared",
    "climb",
    "close",
    "cold",
    "column",
    "combat",
    "comm",
    "commencing",
    "comms",
    "complete",
    "connect",
    "contact",
    "context",
    "control",
    "controls",
    "copy",
    "countermeasures",
    "course",
    "crew",
    "cruise",
    "damage",
    "defense",
    "departure",
    "designate",
    "designation",
    "destination",
    "direct",
    "disable",
    "disconnect",
    "display",
    "divert",
    "double",
    "downwind",
    "echelon",
    "eject",
    "ejection",
    "elevation",
    "emergency",
    "enemy",
    "engage",
    "engine",
    "engines",
    "established",
    "east",
    "external",
    "far",
    "feet",
    "field",
    "final",
    "flare",
    "flares",
    "flight",
    "formation",
    "forward",
    "frequency",
    "friendly",
    "fuel",
    "full",
    "fuse",
    "gate",
    "grid",
    "ground",
    "group",
    "guided",
    "gun",
    "guns",
    "heading",
    "helo",
    "helos",
    "high",
    "hold",
    "home",
    "hostile",
    "hot",
    "hover",
    "inbound",
    "initial",
    "instrument",
    "interrogate",
    "jammer",
    "jettison",
    "kneeboard",
    "ladder",
    "landing",
    "laser",
    "launch",
    "left",
    "level",
    "line",
    "link",
    "load",
    "lock",
    "low",
    "manual",
    "mark",
    "marker",
    "meatball",
    "mid",
    "mine",
    "mission",
    "missile",
    "missiles",
    "mode",
    "monitor",
    "movers",
    "multiple",
    "music",
    "narrow",
    "nearest",
    "negative",
    "normal",
    "nose",
    "notes",
    "off",
    "on",
    "options",
    "north",
    "northeast",
    "northwest",
    "orbit",
    "overhead",
    "overwatch",
    "parking",
    "picture",
    "pilot",
    "pitot",
    "platform",
    "point",
    "power",
    "precontact",
    "preset",
    "program",
    "proxy",
    "pulse",
    "quantity",
    "radar",
    "radio",
    "range",
    "rear",
    "receive",
    "record",
    "refuel",
    "refueling",
    "relative",
    "release",
    "remarks",
    "repair",
    "report",
    "restore",
    "return",
    "right",
    "ripple",
    "rocket",
    "rockets",
    "route",
    "runway",
    "safe",
    "scan",
    "search",
    "sector",
    "sectors",
    "settings",
    "ships",
    "shutdown",
    "silence",
    "single",
    "smoke",
    "south",
    "southeast",
    "southwest",
    "speed",
    "spike",
    "spoilers",
    "spread",
    "stab",
    "standby",
    "starboard",
    "startup",
    "state",
    "status",
    "steps",
    "steerpoint",
    "stop",
    "stored",
    "stores",
    "strafe",
    "straight",
    "surface",
    "systems",
    "tail",
    "target",
    "targets",
    "tanker",
    "tasking",
    "taxi",
    "takeoff",
    "tally",
    "terminal",
    "time",
    "tower",
    "track",
    "tracking",
    "traffic",
    "trail",
    "transmission",
    "transmit",
    "trim",
    "tune",
    "turn",
    "undesignate",
    "unlock",
    "unknown",
    "vector",
    "vectors",
    "vehicle",
    "vehicles",
    "visual",
    "waypoint",
    "weapon",
    "weapons",
    "wedge",
    "west",
    "wheelchocks",
    "wide",
}

STOP_WORDS = {
    "a",
    "about",
    "above",
    "again",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "back",
    "be",
    "below",
    "both",
    "by",
    "can",
    "current",
    "de",
    "do",
    "dont",
    "for",
    "from",
    "go",
    "going",
    "good",
    "here",
    "i",
    "in",
    "is",
    "it",
    "let",
    "me",
    "more",
    "my",
    "near",
    "next",
    "no",
    "not",
    "now",
    "al",
    "begin",
    "cancel",
    "call",
    "calls",
    "deactivate",
    "eight",
    "eighteen",
    "eighty",
    "eleven",
    "enter",
    "extend",
    "fifteen",
    "fifty",
    "five",
    "force",
    "forty",
    "four",
    "fourteen",
    "hundred",
    "know",
    "looking",
    "nine",
    "nineteen",
    "ninety",
    "of",
    "one",
    "only",
    "or",
    "our",
    "out",
    "page",
    "place",
    "please",
    "previous",
    "ready",
    "remain",
    "remove",
    "repeat",
    "request",
    "requesting",
    "required",
    "restart",
    "resume",
    "retract",
    "say",
    "see",
    "select",
    "selected",
    "selector",
    "set",
    "seven",
    "seventeen",
    "seventy",
    "show",
    "silent",
    "six",
    "sixteen",
    "sixty",
    "some",
    "start",
    "sure",
    "switch",
    "take",
    "talk",
    "ten",
    "that",
    "the",
    "there",
    "thirteen",
    "thirty",
    "this",
    "thousand",
    "three",
    "to",
    "toggle",
    "twelve",
    "twenty",
    "two",
    "up",
    "use",
    "view",
    "was",
    "we",
    "what",
    "will",
    "with",
    "yes",
    "you",
    "your",
    "yours",
}

LOW_VALUE_WORDS = {
    "after",
    "ahead",
    "assistance",
    "assisted",
    "before",
    "captured",
    "correction",
    "default",
    "delete",
    "dictate",
    "edit",
    "end",
    "fine",
    "hints",
    "ice",
    "incentive",
    "information",
    "insert",
    "little",
    "log",
    "minus",
    "mystery",
    "part",
    "plus",
    "queue",
    "recommend",
    "review",
    "server",
    "small",
    "subtitles",
    "tab",
    "test",
    "testing",
    "thing",
    "tiny",
    "waiting",
    "war",
    "work",
}


def clean_term(value: object) -> str:
    term = html.unescape(str(value))
    term = re.sub(r"<[^>]+>", " ", term)
    term = term.replace("\ufeff", "")
    term = re.sub(r"\([^)]*mHz[^)]*\)", " ", term, flags=re.IGNORECASE)
    term = term.strip().strip("*").strip()
    # Unwrap a term that is a single bracketed group ("[Channel]" -> "Channel"), but leave
    # brackets that delimit placeholders inside a phrase alone, so multi-slot command
    # templates ("[Radio] [Channel] [1..18]") are not mangled into unbalanced text.
    while (
        len(term) >= 2
        and term[0] == "["
        and term[-1] == "]"
        and "[" not in term[1:-1]
        and "]" not in term[1:-1]
    ):
        term = term[1:-1].strip()
    term = term.replace("_", " ")
    term = re.sub(r"\s+", " ", term).strip()
    term = unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode("ascii")
    return term.strip(" ;,")


def add_term(terms: list[str], value: object) -> None:
    term = clean_term(value)
    if not term or len(term) < 2:
        return
    if "[" in term or "]" in term or ".." in term:
        return
    if re.fullmatch(r"[0-9.\-+ /]+", term):
        return

    terms.append(term)

    if "-" in term:
        terms.append(clean_term(term.replace("-", " ")))

    if re.search(r"[a-z][A-Z]", term):
        terms.append(clean_term(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", term)))


def parse_keywords_txt(vaicom_root: Path, terms: list[str]) -> None:
    path = vaicom_root / "Export" / "keywords.txt"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    for chunk in re.findall(r"\[([^\[\]]*)\]", text):
        for part in chunk.split(";"):
            add_term(terms, part)

    for part in text.replace("[", ";").replace("]", ";").split(";"):
        add_term(terms, part)


class _KeywordsHtmlParser(HTMLParser):
    """Tolerant reader for VAICOM's generated ``Export/keywords.html`` alias table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.aliases: list[str] = []
        self.rows: list[tuple[str, str, tuple[str, ...]]] = []
        self._in_row = False
        self._current_cell: str | None = None
        self._cell_parts: list[str] = []
        self._action = ""
        self._group = ""
        self._aliases: list[str] = []
        self._in_alias_cell = False
        self._alias_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "tr":
            self._in_row = True
            self._current_cell = None
            self._cell_parts = []
            self._action = ""
            self._group = ""
            self._aliases = []
        elif tag == "td" and "action" in classes:
            self._current_cell = "action"
            self._cell_parts = []
        elif tag == "td" and "group" in classes:
            self._current_cell = "group"
            self._cell_parts = []
        elif tag == "td" and "aliases" in classes:
            self._current_cell = "aliases"
            self._in_alias_cell = True
        elif self._in_alias_cell and tag == "span" and "alias-item" in classes:
            self._alias_parts = []

    def handle_data(self, data: str) -> None:
        if self._alias_parts is not None:
            self._alias_parts.append(data)
        elif self._current_cell in {"action", "group"}:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._alias_parts is not None:
            alias = " ".join("".join(self._alias_parts).split())
            if alias:
                self.aliases.append(alias)
                self._aliases.append(alias)
            self._alias_parts = None
        elif tag == "td":
            if self._current_cell == "action":
                self._action = " ".join("".join(self._cell_parts).split())
            elif self._current_cell == "group":
                self._group = " ".join("".join(self._cell_parts).split())
            self._current_cell = None
            self._cell_parts = []
            self._in_alias_cell = False
            self._alias_parts = None
        elif tag == "tr" and self._in_row:
            if self._aliases:
                self.rows.append((self._action, self._group, tuple(self._aliases)))
            self._in_row = False


def parse_keywords_html(vaicom_root: Path, terms: list[str]) -> None:
    path = vaicom_root / "Export" / "keywords.html"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    parser = _KeywordsHtmlParser()
    parser.feed(text)
    for alias in parser.aliases:
        add_term(terms, alias)


def parse_voiceattack_profiles(vaicom_root: Path, terms: list[str]) -> None:
    profile_paths = [
        *sorted((vaicom_root / "Profiles").glob("*.vap")),
        *sorted((vaicom_root / "Export").glob("*.vap")),
    ]

    for path in profile_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for command_string in re.findall(
            r"<CommandString>(.*?)</CommandString>", text, flags=re.IGNORECASE | re.DOTALL
        ):
            for part in html.unescape(command_string).split(";"):
                add_term(terms, part)


def parse_icao_overrides(saved_games: Path, terms: list[str]) -> None:
    path = saved_games / "Scripts" / "VAICOMPRO" / "ICAOOverrides.lua"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    for name, code in re.findall(r'\["([^"]+)"\]\s*=\s*"([^"]*)"', text):
        add_term(terms, name.title())
        if code.strip():
            add_term(terms, code.strip())


def walk_json_terms(value: object, terms: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"name", "label", "option"}:
                add_term(terms, item)
            elif key == "path":
                for part in str(item).split(">"):
                    add_term(terms, part)
            else:
                walk_json_terms(item, terms)
    elif isinstance(value, list):
        for item in value:
            walk_json_terms(item, terms)


def parse_wso_caches(vaicom_root: Path, terms: list[str]) -> None:
    for filename in ("WSO_DIALOG_CACHE_RAW.json", "WSO_ACTION_CACHE_RAW.json"):
        path = vaicom_root / "Logs" / filename
        if not path.is_file():
            continue
        # VAICOM may leave an empty or half-written cache (e.g. between sessions). Skip it
        # rather than letting one malformed file abort the whole vocabulary refresh.
        raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        walk_json_terms(payload, terms)


def parse_vaicom_log(vaicom_root: Path, terms: list[str]) -> None:
    """Parse historical F10 import lines from VAICOM's log.

    Kept for compatibility with old tooling, but the packaged permanent generator no
    longer calls it: live F10 menu items are mission-scoped and belong in the ephemeral
    mission overlay handled by ``infrastructure.vocabulary.mission_f10``.
    """
    path = vaicom_root / "Logs" / "VAICOMPRO.log"
    if not path.is_file():
        return

    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in re.findall(r"Set menu F10 item:\s*Action\s+(.+?),\s*ActionIndex", text):
        add_term(terms, match)


def dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = clean_term(term)
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def split_words(term: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", term)
    spaced = spaced.replace("'", "")
    return re.findall(r"[A-Za-z]+", spaced)


def canonical_word(word: str) -> str:
    lower = word.lower()
    if lower in COMMON_WORDS:
        return lower
    upper = word.upper()
    if upper in TECHNICAL_WORDS:
        return upper
    if len(word) > 1 and word.isupper():
        return word
    return word[:1].upper() + word[1:].lower()


def is_proper_word(word: str) -> bool:
    lower = word.lower()
    return (
        word in HIGH_PRIORITY_PROPER_WORDS
        or word in TECHNICAL_WORDS
        or (len(word) > 1 and word.isupper())
        or lower not in COMMON_WORDS
    )


def is_code_word(word: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3,6}", word)) and word not in TECHNICAL_WORDS


def dedupe_words(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    words: list[str] = []
    for term in terms:
        for raw_word in split_words(term):
            if any(char.isdigit() for char in raw_word):
                continue
            lower = raw_word.lower()
            if len(lower) < 2 or lower in STOP_WORDS or lower in LOW_VALUE_WORDS:
                continue

            word = canonical_word(raw_word)
            if is_code_word(word):
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            words.append(word)
    return words


def word_priority(word: str, original_index: int) -> tuple[int, int, str]:
    lower = word.lower()
    if word in TECHNICAL_WORDS:
        rank = 0
    elif lower in HIGH_PRIORITY_COMMAND_WORDS:
        rank = 1
    elif word in HIGH_PRIORITY_PROPER_WORDS:
        rank = 2
    elif lower in COMMON_WORDS:
        rank = 3
    elif is_proper_word(word):
        rank = 4
    else:
        rank = 5
    return rank, original_index, word.lower()


def generate_keyterms(
    vaicom_root: Path, saved_games: Path, max_keyterms: int = DEFAULT_MAX_KEYTERMS
) -> list[str]:
    terms: list[str] = []
    parse_keywords_txt(vaicom_root, terms)
    parse_keywords_html(vaicom_root, terms)
    parse_voiceattack_profiles(vaicom_root, terms)
    parse_icao_overrides(saved_games, terms)
    parse_wso_caches(vaicom_root, terms)

    deduped = dedupe_words(dedupe_terms(terms))
    return [
        term
        for _, term in sorted(
            enumerate(deduped),
            key=lambda item: word_priority(item[1], item[0]),
        )
    ][:max_keyterms]


def write_keyterms(path: Path, keyterms: list[str], vaicom_root: Path, saved_games: Path) -> None:
    lines = [
        "# Generated VAICOM/DCS keyterms for speech-to-text biasing.",
        f"# Source VAICOM root: {vaicom_root}",
        f"# Source DCS Saved Games: {saved_games}",
        "# Refresh with: python tools/generate_vaicom_keyterms.py --vaicom-root <VAICOMPRO>",
        "# One unique word per line. Composed phrases, numeric tokens, and code-only terms are removed.",
        "# Ordering is priority-sensitive: technical acronyms, high-value command words, callsigns,",
        "# common DCS terms, then selected proper names. Low-value UI/noise terms are removed.",
        f"# Word count: {len(keyterms)}",
        "",
    ]
    lines.extend(keyterms)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _discovery_candidates() -> list[Path]:
    """Return candidate VAICOM install roots in priority order (ADR-0005).

    The ``VAICOMPRO_DIR`` env override comes first, then ``VAICOM*`` folders found under
    the common VoiceAttack ``Apps`` locations (per-user, standalone, and Steam libraries).
    """
    candidates: list[Path] = []
    env_override = os.getenv("VAICOMPRO_DIR")
    if env_override:
        candidates.append(Path(env_override))

    bases = [
        *_appdata_roots(),
        *_program_files_roots(),
        *_steam_common_roots(),
    ]
    app_suffixes = [
        Path("VoiceAttack2") / "Apps",
        Path("VoiceAttack 2") / "Apps",
        Path("VoiceAttack") / "Apps",
        Path("Apps"),
    ]
    for base in bases:
        for suffix in app_suffixes:
            apps_dir = Path(base) / suffix
            if apps_dir.is_dir():
                candidates.extend(sorted(apps_dir.glob("VAICOM*")))
    return _unique_paths(candidates)


def _appdata_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        env_value = os.getenv(env_name)
        if env_value:
            roots.append(Path(env_value))
    return _unique_paths(roots)


def _program_files_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        env_value = os.getenv(env_name)
        if env_value:
            roots.append(Path(env_value))
    return _unique_paths(roots)


def _steam_common_roots() -> list[Path]:
    common_roots = [
        Path(r"C:\Program Files (x86)\Steam") / "steamapps" / "common",
        Path(r"C:\Program Files\Steam") / "steamapps" / "common",
    ]
    for steam_root in _steam_roots():
        for library_root in _steam_library_roots(steam_root):
            common_roots.append(library_root / "steamapps" / "common")
    return _unique_paths(common_roots)


def _steam_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import winreg
    except ImportError:
        return roots

    registry_locations = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    )
    for hive, key_path in registry_locations:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _kind = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value:
                        roots.append(Path(value))
        except OSError:
            continue
    return _unique_existing_paths(roots)


def _steam_library_roots(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return _unique_existing_paths(libraries)

    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(Path(match.group(1).replace(r"\\", "\\")))
    return _unique_existing_paths(libraries)


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        unique.setdefault(str(path).lower(), path)
    return list(unique.values())


def _unique_existing_paths(paths: list[Path]) -> list[Path]:
    return _unique_paths([path for path in paths if path.is_dir()])


def _looks_like_vaicom_root(path: Path) -> bool:
    """Whether ``path`` looks like a VAICOM install (has the files we parse)."""
    return path.is_dir() and (
        (path / "Export" / "keywords.txt").is_file()
        or (path / "Profiles").is_dir()
        or bool(list(path.glob("*.vap")))
    )


def discover_vaicom_root() -> Path | None:
    """Auto-discover a VAICOM install (env override + common locations, ADR-0005)."""
    for candidate in _discovery_candidates():
        if _looks_like_vaicom_root(candidate):
            return candidate
    return None


def _split_alternates(command_string: str) -> list[str]:
    """Split a CommandString on top-level ``;`` only — not inside ``[...]`` groups.

    VAICOM groups spoken alternatives inside brackets (``[Alpha;Bravo;Zulu]``); splitting the
    whole string on ``;`` would shatter those groups into dangling-bracket fragments
    (``[Alpha``, ``Zulu] [0..1]``). Splitting only at bracket depth zero keeps each grammar
    slot intact so :func:`_strip_placeholders` can drop it cleanly.
    """
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(command_string):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            parts.append(command_string[start:index])
            start = index + 1
    parts.append(command_string[start:])
    return parts


_AIRCRAFT_TAG_RE = re.compile(
    r"\b(?:F/A-\d+[A-Z]*|[A-Z]{1,4}-\d{1,3}[A-Z]*(?:-\d+[A-Z]*)?)\b",
    re.IGNORECASE,
)


def collect_phrases(vaicom_root: Path, saved_games: Path) -> list[str]:
    """Collect candidate command phrases (whole, not word-split) for the snap index.

    The authoritative spoken commands are the VoiceAttack ``<CommandString>`` entries
    (``;`` separates alternate spoken forms of one command); the ``keywords.txt`` bracket
    chunks add recipient/command vocabulary. Each form is split on top-level ``;`` only (not
    inside ``[...]`` alternation groups, which would shatter them) and cleaned, but kept
    whole — including its ``[...]`` parameter slots, which show the command's arguments.
    """
    phrases: list[str] = []

    profile_paths = [
        *sorted((vaicom_root / "Profiles").glob("*.vap")),
        *sorted((vaicom_root / "Export").glob("*.vap")),
    ]
    for path in profile_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for command_string in re.findall(
            r"<CommandString>(.*?)</CommandString>", text, flags=re.IGNORECASE | re.DOTALL
        ):
            for part in _split_alternates(html.unescape(command_string)):
                phrases.append(clean_term(part))

    keywords_path = vaicom_root / "Export" / "keywords.txt"
    if keywords_path.is_file():
        text = keywords_path.read_text(encoding="utf-8", errors="ignore")
        for chunk in re.findall(r"\[([^\[\]]*)\]", text):
            for part in chunk.split(";"):
                phrases.append(clean_term(part))

    keywords_html_path = vaicom_root / "Export" / "keywords.html"
    if keywords_html_path.is_file():
        text = keywords_html_path.read_text(encoding="utf-8", errors="ignore")
        parser = _KeywordsHtmlParser()
        parser.feed(text)
        for alias in parser.aliases:
            phrases.append(clean_term(alias))

    return phrases


def _is_command_phrase(phrase: str) -> bool:
    """Whether a cleaned phrase belongs in the snap index.

    Keep multi-word phrases of a sane length; single words are handled by the keyterms +
    per-token fuzzy step and would over-trigger the snapper. ``[...]`` parameter slots are
    kept (they document the command's arguments) and count toward the word/length budget.
    """
    words = phrase.split()
    return 2 <= len(words) <= 8 and len(phrase) <= 60


def collect_command_catalog_entries(
    vaicom_root: Path, saved_games: Path
) -> list[CommandCatalogEntry]:
    """Collect candidate command phrases with source/group/aircraft metadata.

    The collected phrases intentionally mirror :func:`collect_phrases`; the extra fields
    are a UI sidecar only and never change what the snapper accepts.
    """
    entries: list[CommandCatalogEntry] = []

    profile_paths = [
        *sorted((vaicom_root / "Profiles").glob("*.vap")),
        *sorted((vaicom_root / "Export").glob("*.vap")),
    ]
    for path in profile_paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        profile_name = _first_xml_value(text, "Name")
        source_label = path.name
        for command in re.findall(
            r"<Command\b.*?</Command>", text, flags=re.IGNORECASE | re.DOTALL
        ):
            command_string = _first_xml_value(command, "CommandString")
            if not command_string:
                continue
            category = _first_xml_value(command, "Category")
            groups = _non_empty((category, profile_name))
            aircraft = _aircraft_tags((*groups, source_label))
            for part in _split_alternates(html.unescape(command_string)):
                entries.append(
                    CommandCatalogEntry(
                        phrase=clean_term(part),
                        groups=groups,
                        aircraft=aircraft,
                        sources=(source_label,),
                    )
                )

    keywords_path = vaicom_root / "Export" / "keywords.txt"
    if keywords_path.is_file():
        text = keywords_path.read_text(encoding="utf-8", errors="ignore")
        for chunk in re.findall(r"\[([^\[\]]*)\]", text):
            for part in chunk.split(";"):
                entries.append(
                    CommandCatalogEntry(
                        phrase=clean_term(part),
                        sources=(keywords_path.name,),
                    )
                )

    keywords_html_path = vaicom_root / "Export" / "keywords.html"
    if keywords_html_path.is_file():
        text = keywords_html_path.read_text(encoding="utf-8", errors="ignore")
        parser = _KeywordsHtmlParser()
        parser.feed(text)
        for _action, group, aliases in parser.rows:
            groups = _non_empty((group,))
            aircraft = _aircraft_tags(groups)
            for alias in aliases:
                entries.append(
                    CommandCatalogEntry(
                        phrase=clean_term(alias),
                        groups=groups,
                        aircraft=aircraft,
                        sources=(keywords_html_path.name,),
                    )
                )

    return entries


def generate_command_catalog(
    vaicom_root: Path, saved_games: Path, max_phrases: int = DEFAULT_MAX_PHRASES
) -> list[CommandCatalogEntry]:
    """Build the sorted command catalog sidecar for the UI command browser."""
    return _dedupe_catalog_entries(
        entry
        for entry in collect_command_catalog_entries(vaicom_root, saved_games)
        if _is_command_phrase(entry.phrase)
    )[:max_phrases]


def generate_phrase_index(
    vaicom_root: Path, saved_games: Path, max_phrases: int = DEFAULT_MAX_PHRASES
) -> list[str]:
    """Build the deduped, sorted phrase index of valid command phrases (ADR-0011)."""
    return [
        entry.phrase
        for entry in generate_command_catalog(
            vaicom_root,
            saved_games,
            max_phrases=max_phrases,
        )
    ]


def write_phrase_index(
    path: Path, phrases: list[str], vaicom_root: Path, saved_games: Path
) -> None:
    """Write the phrase index the Axis B snapper loads (ADR-0011 / ADR-0005)."""
    lines = [
        "# Generated VAICOM/DCS command phrase index for the Axis B phrase snapper (ADR-0011).",
        f"# Source VAICOM root: {vaicom_root}",
        f"# Source DCS Saved Games: {saved_games}",
        "# Refresh with: python tools/generate_vaicom_keyterms.py",
        "# One valid command phrase per line (whole; alternates were split on ';').",
        f"# Phrase count: {len(phrases)}",
        "",
    ]
    lines.extend(phrases)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_command_catalog(
    path: Path,
    entries: list[CommandCatalogEntry],
    vaicom_root: Path,
    saved_games: Path,
) -> None:
    """Write the UI command catalog sidecar next to the flat phrase index."""
    payload = {
        "version": COMMAND_CATALOG_VERSION,
        "source_vaicom_root": str(vaicom_root),
        "source_saved_games": str(saved_games),
        "entries": [
            {
                "phrase": entry.phrase,
                "groups": list(entry.groups),
                "aircraft": list(entry.aircraft),
                "sources": list(entry.sources),
            }
            for entry in entries
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _first_xml_value(text: str, tag: str) -> str:
    match = re.search(
        rf"<{tag}\b[^>]*>(.*?)</{tag}>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return ""
    return clean_term(match.group(1))


def _non_empty(values: Iterable[str]) -> tuple[str, ...]:
    return _unique_strings(value for value in values if value)


def _aircraft_tags(values: Iterable[str]) -> tuple[str, ...]:
    tags: list[str] = []
    for value in values:
        for match in _AIRCRAFT_TAG_RE.finditer(value):
            tags.append(match.group(0).upper())
    return _unique_strings(tags)


def _dedupe_catalog_entries(entries: Iterable[CommandCatalogEntry]) -> list[CommandCatalogEntry]:
    merged: dict[str, CommandCatalogEntry] = {}
    order: list[str] = []
    for entry in entries:
        phrase = clean_term(entry.phrase)
        if not phrase:
            continue
        key = phrase.casefold()
        if key not in merged:
            order.append(key)
            merged[key] = CommandCatalogEntry(
                phrase=phrase,
                groups=_unique_strings(entry.groups),
                aircraft=_unique_strings(entry.aircraft),
                sources=_unique_strings(entry.sources),
            )
            continue
        previous = merged[key]
        merged[key] = CommandCatalogEntry(
            phrase=previous.phrase,
            groups=_unique_strings((*previous.groups, *entry.groups)),
            aircraft=_unique_strings((*previous.aircraft, *entry.aircraft)),
            sources=_unique_strings((*previous.sources, *entry.sources)),
        )
    return sorted((merged[key] for key in order), key=lambda entry: entry.phrase.lower())


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = " ".join(str(value).split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return tuple(unique)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate STT keyterms + the snap phrase index from a local VAICOM install."
    )
    parser.add_argument(
        "--vaicom-root",
        type=Path,
        default=None,
        help="VAICOM install root. Auto-discovered (VAICOMPRO_DIR + common locations) if omitted.",
    )
    parser.add_argument(
        "--saved-games",
        type=Path,
        default=Path(os.getenv("DCS_SAVED_GAMES", DEFAULT_DCS_SAVED_GAMES)),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="Output directory (defaults to the per-user VAIVOX data dir).",
    )
    parser.add_argument("--keyterms-output", type=Path, default=None)
    parser.add_argument("--phrase-index-output", type=Path, default=None)
    parser.add_argument("--command-catalog-output", type=Path, default=None)
    parser.add_argument("--max-terms", type=int, default=DEFAULT_MAX_KEYTERMS)
    parser.add_argument("--max-phrases", type=int, default=DEFAULT_MAX_PHRASES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    vaicom_root = args.vaicom_root or discover_vaicom_root()
    if vaicom_root is None:
        raise SystemExit(
            "No VAICOM install found. Set VAICOMPRO_DIR or pass --vaicom-root "
            "(looked for VAICOM* under VoiceAttack 'Apps' in Program Files / Steam)."
        )
    if not vaicom_root.is_dir():
        raise SystemExit(f"VAICOM root does not exist: {vaicom_root}")

    keyterms_output = args.keyterms_output or (args.data_dir / KEYTERMS_FILE)
    phrase_output = args.phrase_index_output or (args.data_dir / PHRASE_INDEX_FILE)
    catalog_output = args.command_catalog_output or (args.data_dir / COMMAND_CATALOG_FILE)

    keyterms = generate_keyterms(vaicom_root, args.saved_games, args.max_terms)
    write_keyterms(keyterms_output, keyterms, vaicom_root, args.saved_games)

    catalog = generate_command_catalog(vaicom_root, args.saved_games, args.max_phrases)
    phrases = [entry.phrase for entry in catalog]
    write_phrase_index(phrase_output, phrases, vaicom_root, args.saved_games)
    write_command_catalog(catalog_output, catalog, vaicom_root, args.saved_games)

    print(f"VAICOM root: {vaicom_root}")
    print(f"Wrote {len(keyterms)} keyterms to {keyterms_output}")
    print(f"Wrote {len(phrases)} command phrases to {phrase_output}")
    print(f"Wrote {len(catalog)} command metadata entries to {catalog_output}")


if __name__ == "__main__":
    main()
