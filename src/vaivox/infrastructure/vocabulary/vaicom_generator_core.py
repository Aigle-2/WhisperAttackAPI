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
from pathlib import Path

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
    the common VoiceAttack ``Apps`` locations (standalone + Steam).
    """
    candidates: list[Path] = []
    env_override = os.getenv("VAICOMPRO_DIR")
    if env_override:
        candidates.append(Path(env_override))

    bases = [
        os.getenv("PROGRAMFILES"),
        os.getenv("PROGRAMFILES(X86)"),
        os.getenv("PROGRAMW6432"),
        r"C:\Program Files (x86)\Steam\steamapps\common",
        r"C:\Program Files\Steam\steamapps\common",
    ]
    app_suffixes = [Path("VoiceAttack 2") / "Apps", Path("VoiceAttack") / "Apps", Path("Apps")]
    for base in bases:
        if not base:
            continue
        for suffix in app_suffixes:
            apps_dir = Path(base) / suffix
            if apps_dir.is_dir():
                candidates.extend(sorted(apps_dir.glob("VAICOM*")))
    return candidates


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

    return phrases


def _is_command_phrase(phrase: str) -> bool:
    """Whether a cleaned phrase belongs in the snap index.

    Keep multi-word phrases of a sane length; single words are handled by the keyterms +
    per-token fuzzy step and would over-trigger the snapper. ``[...]`` parameter slots are
    kept (they document the command's arguments) and count toward the word/length budget.
    """
    words = phrase.split()
    return 2 <= len(words) <= 8 and len(phrase) <= 60


def generate_phrase_index(
    vaicom_root: Path, saved_games: Path, max_phrases: int = DEFAULT_MAX_PHRASES
) -> list[str]:
    """Build the deduped, sorted phrase index of valid command phrases (ADR-0011)."""
    seen: set[str] = set()
    index: list[str] = []
    for phrase in collect_phrases(vaicom_root, saved_games):
        if not _is_command_phrase(phrase):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        index.append(phrase)
    index.sort(key=str.lower)
    return index[:max_phrases]


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

    keyterms = generate_keyterms(vaicom_root, args.saved_games, args.max_terms)
    write_keyterms(keyterms_output, keyterms, vaicom_root, args.saved_games)

    phrases = generate_phrase_index(vaicom_root, args.saved_games, args.max_phrases)
    write_phrase_index(phrase_output, phrases, vaicom_root, args.saved_games)

    print(f"VAICOM root: {vaicom_root}")
    print(f"Wrote {len(keyterms)} keyterms to {keyterms_output}")
    print(f"Wrote {len(phrases)} command phrases to {phrase_output}")


if __name__ == "__main__":
    main()
