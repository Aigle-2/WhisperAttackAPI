"""Resolve concrete utterances against VoiceAttack dynamic command patterns.

VoiceAttack profiles can define commands with bracketed slots, for example
``Radar Focus Target [1..20]`` or
``[WSO; Wizzo; Boots;] [Set; Select] TACAN [channel] [zero;0;1] [0..9] [0..9]``.
The generated VAICOM phrase index keeps those patterns as text, but dispatch must send a
concrete utterance that VoiceAttack can execute. This adapter decorates the normal
command-surface resolver with a generic bracket-pattern matcher.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from vaivox.domain.commands.model import (
    CommandResolution,
    CommandResolutionDecision,
    CommandSurface,
    VoiceAttackCommand,
)

_BRACKET_RE = re.compile(r"\[([^\[\]]*)\]")
_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_RANGE_RE = re.compile(r"^(\d+)\s*\.\.\s*(\d+)$")
_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "niner": "9",
}
_ADDRESS_PREFIX_TOKENS = {
    "boots",
    "george",
    "gunner",
    "jester",
    "pilot",
    "rio",
    "wizzo",
    "wso",
}
_PHONETIC_ALPHABET_KEYS = {
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "x ray",
    "yankee",
    "zulu",
}


class _ResolverSnapshot(Protocol):
    """Command-surface resolver delegated to after dynamic-pattern matching."""

    @property
    def surfaces(self) -> tuple[CommandSurface, ...]:
        """The command surfaces this snapshot resolves against."""

    def resolve(self, text: str) -> CommandResolution:
        """Resolve ``text`` to a command surface, or abstain/raw."""


@dataclass(frozen=True)
class _Choice:
    text: str
    tokens: tuple[str, ...]
    range_start: int | None = None
    range_end: int | None = None

    @property
    def is_range(self) -> bool:
        """Whether this choice is a numeric ``N..M`` range."""
        return self.range_start is not None and self.range_end is not None


@dataclass(frozen=True)
class _Literal:
    text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class _Slot:
    choices: tuple[_Choice, ...]
    optional: bool

    @property
    def is_numeric(self) -> bool:
        """Whether every non-empty choice is a numeric range."""
        return bool(self.choices) and all(_is_numeric_choice(choice) for choice in self.choices)


type _Element = _Literal | _Slot


@dataclass(frozen=True)
class _PatternMatch:
    surface: CommandSurface
    command_text: str
    matched_tokens: int
    defaulted_slots: int
    unmatched_tokens: int
    aircraft_priority: int

    @property
    def rank(self) -> tuple[int, int, int, int, int]:
        """Sort key; higher means a safer, more specific match."""
        return (
            self.aircraft_priority,
            self.matched_tokens,
            -self.defaulted_slots,
            -self.unmatched_tokens,
            len(self.command_text),
        )


class VoiceAttackDynamicCommandMatcher:
    """Decorate a static resolver with generic VoiceAttack bracket-pattern matching."""

    def __init__(self, delegate: _ResolverSnapshot, get_current_aircraft: CallableAircraft) -> None:
        """Wire the delegate resolver and current-aircraft provider."""
        self._delegate = delegate
        self._get_current_aircraft = get_current_aircraft

    @property
    def surfaces(self) -> tuple[CommandSurface, ...]:
        """The delegate's command surfaces."""
        return self._delegate.surfaces

    def resolve(self, text: str) -> CommandResolution:
        """Resolve dynamic profile patterns before falling back to the regular resolver."""
        match = _best_dynamic_match(text, self._delegate.surfaces, self._get_current_aircraft())
        if match is not None:
            surface = CommandSurface(
                id=match.surface.id,
                label=match.surface.label,
                aliases=match.surface.aliases,
                source=match.surface.source,
                scope=match.surface.scope,
                dispatch_target=VoiceAttackCommand(match.command_text),
                semantic_aliases=match.surface.semantic_aliases,
                available=match.surface.available,
                unavailable_reason=match.surface.unavailable_reason,
            )
            return CommandResolution(
                CommandResolutionDecision.RESOLVED,
                surface=surface,
                matched_alias=match.surface.label,
                score=100.0,
            )
        return self._delegate.resolve(text)


type CallableAircraft = Callable[[], str | None]


def format_voiceattack_pattern(pattern: str) -> str:
    """Return a player-readable rendering of a VoiceAttack command pattern.

    The raw pattern remains the execution contract, but the Commands window should not
    force users to mentally parse VoiceAttack slots. This keeps the transformation generic:
    alternatives become slash-separated options and adjacent numeric ranges become compact
    placeholders.
    """
    if not _is_dynamic_pattern(pattern):
        return " ".join(pattern.split())
    elements = _drop_leading_address_slot(_parse_pattern(pattern))
    numeric_runs = _numeric_runs(elements)
    parts: list[str] = []
    index = 0
    while index < len(elements):
        element = elements[index]
        if isinstance(element, _Literal):
            parts.append(element.text)
            index += 1
            continue

        letter_run = _phonetic_letter_run(elements, index)
        if letter_run:
            parts.append(_format_phonetic_letter_run(letter_run))
            index += letter_run
            continue

        run = numeric_runs.get(index)
        if run is not None:
            parts.append(_format_numeric_run(run))
            index += len(run)
            continue

        rendered = _format_slot(element)
        if rendered:
            parts.append(rendered)
        index += 1
    return " ".join(parts) or " ".join(pattern.split())


def voiceattack_pattern_matches(pattern: str, query: str) -> bool:
    """Return whether ``query`` is a concrete example of ``pattern``."""
    if not _is_dynamic_pattern(pattern):
        return False
    surface = CommandSurface(
        id="voiceattack:query-probe",
        label=pattern,
        aliases=(),
        source="voiceattack",
        scope="global",
        dispatch_target=VoiceAttackCommand(pattern),
    )
    return _match_pattern(query, surface, current_aircraft=None) is not None


def _best_dynamic_match(
    text: str,
    surfaces: Sequence[CommandSurface],
    current_aircraft: str | None,
) -> _PatternMatch | None:
    matches = [
        match
        for surface in surfaces
        if _is_dynamic_pattern(surface.label)
        for match in [_match_pattern(text, surface, current_aircraft)]
        if match is not None
    ]
    if not matches:
        return None
    return max(matches, key=lambda match: match.rank)


def _match_pattern(
    text: str,
    surface: CommandSurface,
    current_aircraft: str | None,
) -> _PatternMatch | None:
    aircraft_priority = _aircraft_priority(surface.scope, current_aircraft)
    if aircraft_priority < 0:
        return None
    elements = _parse_pattern(surface.label)
    if not elements:
        return None
    tokens = _tokens(text)
    if not tokens:
        return None

    exact = _ordered_match(elements, tokens)
    if exact is not None:
        command_text, matched_tokens, defaulted_slots = exact
        return _PatternMatch(
            surface=surface,
            command_text=command_text,
            matched_tokens=matched_tokens,
            defaulted_slots=defaulted_slots,
            unmatched_tokens=0,
            aircraft_priority=aircraft_priority,
        )

    completed = _completion_match(elements, tokens)
    if completed is None:
        return None
    command_text, matched_tokens, defaulted_slots, unmatched_tokens = completed
    return _PatternMatch(
        surface=surface,
        command_text=command_text,
        matched_tokens=matched_tokens,
        defaulted_slots=defaulted_slots,
        unmatched_tokens=unmatched_tokens,
        aircraft_priority=aircraft_priority,
    )


def _is_dynamic_pattern(pattern: str) -> bool:
    return bool(_BRACKET_RE.search(pattern))


def _parse_pattern(pattern: str) -> tuple[_Element, ...]:
    elements: list[_Element] = []
    position = 0
    for match in _BRACKET_RE.finditer(pattern):
        elements.extend(_literal_elements(pattern[position : match.start()]))
        elements.append(_slot_element(match.group(1)))
        position = match.end()
    elements.extend(_literal_elements(pattern[position:]))
    return tuple(
        element for element in elements if not isinstance(element, _Slot) or element.choices
    )


def _drop_leading_address_slot(elements: tuple[_Element, ...]) -> tuple[_Element, ...]:
    if elements and isinstance(elements[0], _Slot) and _is_address_slot(elements[0]):
        return elements[1:]
    return elements


def _is_address_slot(slot: _Slot) -> bool:
    if not slot.optional or not slot.choices:
        return False
    return all(
        choice.tokens and all(token in _ADDRESS_PREFIX_TOKENS for token in choice.tokens)
        for choice in slot.choices
    )


def _literal_elements(text: str) -> list[_Literal]:
    return [
        _Literal(" ".join(raw_token.split()), _tokens(raw_token))
        for raw_token in _PUNCTUATION.sub(" ", text).split()
    ]


def _slot_element(text: str) -> _Slot:
    choices: list[_Choice] = []
    optional = False
    for raw_choice in text.split(";"):
        choice_text = " ".join(raw_choice.split())
        if not choice_text:
            optional = True
            continue
        range_match = _RANGE_RE.match(choice_text)
        if range_match is not None:
            choices.append(
                _Choice(
                    choice_text,
                    (),
                    int(range_match.group(1)),
                    int(range_match.group(2)),
                )
            )
            continue
        choices.append(_Choice(choice_text, _tokens(choice_text)))
    return _Slot(tuple(choices), optional=optional)


def _ordered_match(
    elements: Sequence[_Element],
    input_tokens: Sequence[str],
) -> tuple[str, int, int] | None:
    """Match tokens in profile order, allowing optional slots to be skipped."""

    def step(
        element_index: int,
        token_index: int,
        output: tuple[str, ...],
        matched: int,
        defaulted: int,
    ) -> tuple[str, int, int] | None:
        if element_index >= len(elements):
            if token_index == len(input_tokens):
                return " ".join(output), matched, defaulted
            return None

        element = elements[element_index]
        if isinstance(element, _Literal):
            if _tokens_match(input_tokens, token_index, element.tokens):
                return step(
                    element_index + 1,
                    token_index + len(element.tokens),
                    (*output, element.text),
                    matched + len(element.tokens),
                    defaulted,
                )
            return None

        for choice in element.choices:
            consumed = _match_choice(input_tokens, token_index, choice)
            if consumed is None:
                continue
            result = step(
                element_index + 1,
                token_index + len(consumed),
                (*output, _choice_output(choice, consumed)),
                matched + len(consumed),
                defaulted,
            )
            if result is not None:
                return result
        if element.optional:
            return step(element_index + 1, token_index, output, matched, defaulted)
        return None

    return step(0, 0, (), 0, 0)


def _completion_match(
    elements: Sequence[_Element],
    input_tokens: Sequence[str],
) -> tuple[str, int, int, int] | None:
    """Fill omitted profile slots when the utterance clearly names the dynamic command."""
    numeric_runs = _numeric_runs(elements)
    if not numeric_runs:
        return None

    number_tokens = [token for token in input_tokens if token.isdigit()]
    if not number_tokens:
        return None

    input_bag = _token_bag(input_tokens)
    output: list[str] = []
    consumed_bag: dict[str, int] = {}
    matched = 0
    defaulted = 0
    number_index = 0
    index = 0
    while index < len(elements):
        element = elements[index]
        if isinstance(element, _Literal):
            if not _consume_required_tokens(input_bag, consumed_bag, element.tokens):
                return None
            output.append(element.text)
            matched += len(element.tokens)
            index += 1
            continue

        run = numeric_runs.get(index)
        if run is not None:
            filled = _fill_numeric_run(run, number_tokens[number_index:])
            if filled is None:
                return None
            run_output, used_numbers = filled
            output.extend(run_output)
            matched += len("".join(number_tokens[number_index : number_index + used_numbers]))
            number_index += used_numbers
            index += len(run)
            continue

        choice = _choose_textual_slot(element, input_bag, consumed_bag)
        if choice is None:
            if element.optional:
                index += 1
                continue
            choice = element.choices[0]
            defaulted += 1
        else:
            matched += len(choice.tokens)
        output.append(choice.text)
        index += 1

    if number_index < len(number_tokens):
        return None
    unmatched = _unmatched_tokens(input_bag, consumed_bag)
    return " ".join(output), matched, defaulted, unmatched


def _numeric_runs(elements: Sequence[_Element]) -> dict[int, tuple[_Slot, ...]]:
    runs: dict[int, tuple[_Slot, ...]] = {}
    index = 0
    while index < len(elements):
        element = elements[index]
        if not isinstance(element, _Slot) or not element.is_numeric:
            index += 1
            continue
        run: list[_Slot] = []
        start = index
        while index < len(elements):
            item = elements[index]
            if not isinstance(item, _Slot) or not item.is_numeric:
                break
            run.append(item)
            index += 1
        runs[start] = tuple(run)
    return runs


def _fill_numeric_run(
    run: Sequence[_Slot],
    number_tokens: Sequence[str],
) -> tuple[tuple[str, ...], int] | None:
    if not number_tokens:
        return None
    ranges = tuple(_range_choice(slot) for slot in run)
    if len(run) == 1:
        start, end = ranges[0]
        best: tuple[str, int] | None = None
        digits = ""
        for index, token in enumerate(number_tokens, start=1):
            digits += token
            value = int(digits)
            if value > end:
                break
            if start <= value <= end:
                best = str(value), index
        if best is not None:
            value_text, used_numbers = best
            return (value_text,), used_numbers
        return None

    if not all(start <= 9 and end <= 9 for start, end in ranges):
        return None
    token_count = 0
    digits = ""
    for candidate in number_tokens:
        if len(digits) + len(candidate) > len(run):
            break
        digits += candidate
        token_count += 1
    if not digits:
        return None
    if len(digits) > len(run):
        return None
    if len(digits) < len(run):
        pad = "".join(str(start) for start, _end in ranges[: len(run) - len(digits)])
        digits = f"{pad}{digits}"
    for digit, (start, end) in zip(digits, ranges, strict=True):
        value = int(digit)
        if not start <= value <= end:
            return None
    return tuple(digits), token_count


def _format_numeric_run(run: Sequence[_Slot]) -> str:
    ranges = tuple(_range_choice(slot) for slot in run)
    if len(ranges) == 1:
        start, end = ranges[0]
        return f"<{start}>" if start == end else f"<{start}-{end}>"
    if all(0 <= start <= 9 and 0 <= end <= 9 for start, end in ranges):
        start_text = "".join(str(start) for start, _end in ranges)
        end_text = "".join(str(end) for _start, end in ranges)
        return f"<{start_text}-{end_text}>"
    return " ".join(f"<{start}-{end}>" if start != end else f"<{start}>" for start, end in ranges)


def _phonetic_letter_run(elements: Sequence[_Element], start: int) -> int:
    count = 0
    for element in elements[start:]:
        if (
            not isinstance(element, _Slot)
            or element.optional
            or not _is_phonetic_alphabet_slot(element)
        ):
            break
        count += 1
    return count


def _is_phonetic_alphabet_slot(slot: _Slot) -> bool:
    return (
        bool(slot.choices)
        and {_choice_key(choice) for choice in slot.choices} == _PHONETIC_ALPHABET_KEYS
    )


def _choice_key(choice: _Choice) -> str:
    return " ".join(choice.tokens)


def _format_phonetic_letter_run(count: int) -> str:
    return "<letter>" if count == 1 else f"<{count} letters>"


def _range_choice(slot: _Slot) -> tuple[int, int]:
    range_choices = [choice for choice in slot.choices if choice.is_range]
    if range_choices:
        choice = range_choices[0]
        if choice.range_start is None or choice.range_end is None:
            raise ValueError("expected numeric range choice")
        return choice.range_start, choice.range_end
    numeric_values = [
        int(choice.tokens[0]) for choice in slot.choices if _is_numeric_choice(choice)
    ]
    if not numeric_values:
        raise ValueError("expected numeric choices")
    return min(numeric_values), max(numeric_values)


def _is_numeric_choice(choice: _Choice) -> bool:
    return choice.is_range or (
        len(choice.tokens) == 1 and choice.tokens[0].isdigit() and len(choice.tokens[0]) == 1
    )


def _format_slot(slot: _Slot) -> str:
    if _is_phonetic_alphabet_slot(slot):
        return "(<letter>)" if slot.optional else "<letter>"
    rendered = "/".join(_format_choice(choice) for choice in slot.choices)
    if not rendered:
        return ""
    return f"({rendered})" if slot.optional else rendered


def _format_choice(choice: _Choice) -> str:
    if choice.is_range:
        if choice.range_start is None or choice.range_end is None:
            return choice.text
        if choice.range_start == choice.range_end:
            return str(choice.range_start)
        return f"<{choice.range_start}-{choice.range_end}>"
    if choice.tokens and all(token.isdigit() for token in choice.tokens):
        return "".join(choice.tokens)
    return choice.text


def _choose_textual_slot(
    slot: _Slot,
    input_bag: dict[str, int],
    consumed_bag: dict[str, int],
) -> _Choice | None:
    candidates = [
        choice
        for choice in slot.choices
        if choice.tokens and _has_available_tokens(input_bag, consumed_bag, choice.tokens)
    ]
    if not candidates:
        return None
    choice = max(candidates, key=lambda item: len(item.tokens))
    _consume_tokens(consumed_bag, choice.tokens)
    return choice


def _match_choice(
    input_tokens: Sequence[str],
    token_index: int,
    choice: _Choice,
) -> tuple[str, ...] | None:
    if choice.is_range:
        if token_index >= len(input_tokens):
            return None
        token = input_tokens[token_index]
        if not token.isdigit():
            return None
        value = int(token)
        if choice.range_start is None or choice.range_end is None:
            return None
        if choice.range_start <= value <= choice.range_end:
            return (token,)
        return None
    if _tokens_match(input_tokens, token_index, choice.tokens):
        return tuple(input_tokens[token_index : token_index + len(choice.tokens)])
    return None


def _choice_output(choice: _Choice, consumed: Sequence[str]) -> str:
    if choice.is_range:
        return " ".join(consumed)
    return choice.text


def _tokens_match(
    input_tokens: Sequence[str],
    token_index: int,
    expected: Sequence[str],
) -> bool:
    return tuple(input_tokens[token_index : token_index + len(expected)]) == tuple(expected)


def _consume_required_tokens(
    input_bag: dict[str, int],
    consumed_bag: dict[str, int],
    tokens: Iterable[str],
) -> bool:
    if not _has_available_tokens(input_bag, consumed_bag, tokens):
        return False
    _consume_tokens(consumed_bag, tokens)
    return True


def _has_available_tokens(
    input_bag: dict[str, int],
    consumed_bag: dict[str, int],
    tokens: Iterable[str],
) -> bool:
    needed = _token_bag(tokens)
    return all(
        input_bag.get(token, 0) - consumed_bag.get(token, 0) >= count
        for token, count in needed.items()
    )


def _consume_tokens(consumed_bag: dict[str, int], tokens: Iterable[str]) -> None:
    for token in tokens:
        consumed_bag[token] = consumed_bag.get(token, 0) + 1


def _unmatched_tokens(input_bag: dict[str, int], consumed_bag: dict[str, int]) -> int:
    return sum(max(0, count - consumed_bag.get(token, 0)) for token, count in input_bag.items())


def _token_bag(tokens: Iterable[str]) -> dict[str, int]:
    bag: dict[str, int] = {}
    for token in tokens:
        bag[token] = bag.get(token, 0) + 1
    return bag


def _aircraft_priority(scope: str, current_aircraft: str | None) -> int:
    tags = tuple(tag.strip() for tag in scope.split(",") if tag.strip() and tag != "global")
    if not tags:
        return 1
    current = _aircraft_key(current_aircraft)
    if not current:
        return 0
    if any(_tags_match(_aircraft_key(tag), current) for tag in tags):
        return 2
    return -1


def _tags_match(tag: str, current: str) -> bool:
    return bool(
        tag and current and (tag == current or current.startswith(tag) or tag.startswith(current))
    )


def _aircraft_key(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(character for character in value.casefold() if character.isalnum())


def _tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    for token in _PUNCTUATION.sub(" ", text.casefold()).split():
        if token in _DIGIT_WORDS:
            tokens.append(_DIGIT_WORDS[token])
        else:
            tokens.append(token)
    return tuple(tokens)
