"""Fuzzy correction of DCS callsigns and phonetic-alphabet tokens.

Uses ``rapidfuzz`` (pure computation, no I/O) to snap long mis-transcribed
tokens back to known vocabulary, keeping DCS and phonetic candidates separate.
"""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import process

_MIN_TOKEN_LENGTH = 6


def correct_dcs_and_phonetics_separately(
    text: str,
    dcs_list: Sequence[str],
    phonetic_list: Sequence[str],
    dcs_threshold: int = 85,
    phonetic_threshold: int = 85,
) -> str:
    """Fuzzy-match each long token against the DCS and phonetic vocabularies.

    Tokens shorter than six characters are left untouched. For longer tokens the
    best-scoring candidate across both vocabularies (above its threshold) wins.

    Args:
        text: The whitespace-tokenized text to correct.
        dcs_list: Candidate DCS callsigns and keywords.
        phonetic_list: The NATO phonetic-alphabet words.
        dcs_threshold: Minimum score (0-100) to accept a DCS match.
        phonetic_threshold: Minimum score (0-100) to accept a phonetic match.

    Returns:
        The text with qualifying tokens replaced by their best vocabulary match.
    """
    tokens = text.split()
    corrected_tokens: list[str] = []
    dcs_lower = [x.lower() for x in dcs_list]
    phon_lower = [x.lower() for x in phonetic_list]

    for token in tokens:
        if len(token) < _MIN_TOKEN_LENGTH:
            corrected_tokens.append(token)
            continue

        t_lower = token.lower()
        dcs_match = process.extractOne(t_lower, dcs_lower, score_cutoff=dcs_threshold)
        phon_match = process.extractOne(t_lower, phon_lower, score_cutoff=phonetic_threshold)
        best_token = token
        best_score = 0.0

        if dcs_match is not None:
            match_name_dcs, score_dcs, _ = dcs_match
            if score_dcs > best_score:
                best_score = score_dcs
                for orig in dcs_list:
                    if orig.lower() == match_name_dcs:
                        best_token = orig
                        break

        if phon_match is not None:
            match_name_phon, score_phon, _ = phon_match
            if score_phon > best_score:
                best_score = score_phon
                for orig in phonetic_list:
                    if orig.lower() == match_name_phon:
                        best_token = orig
                        break

        corrected_tokens.append(best_token)
    return " ".join(corrected_tokens)
