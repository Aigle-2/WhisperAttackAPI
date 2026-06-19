"""Build provider keyterms from config plus structured vocabulary."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from vaivox.application.ports import ReconciliationVocabulary
from vaivox.domain.vocabulary.keyterms import (
    DEFAULT_DCS_KEYTERMS,
    DEFAULT_STT_KEYTERM_SOURCES,
    PHONETIC_ALPHABET,
    BudgetedKeyterms,
    KeytermBudget,
    apply_keyterm_budget,
)
from vaivox.infrastructure.vocabulary.vaicom_keyterms import load_vaicom_keyterms

if TYPE_CHECKING:
    from vaivox.infrastructure.config.settings import VaivoxConfiguration


class SttKeyterms:
    """Resolve and budget STT provider keyterms."""

    def __init__(
        self,
        config: VaivoxConfiguration,
        vocabulary: ReconciliationVocabulary,
    ) -> None:
        """Wire configuration and reconciliation vocabulary sources."""
        self._config = config
        self._vocabulary = vocabulary

    def get_stt_keyterm_sources(self) -> list[str]:
        """Return configured keyterm source names."""
        sources = self._config.get_setting(
            "stt_keyterm_sources", ",".join(DEFAULT_STT_KEYTERM_SOURCES)
        )
        return [source.strip().lower() for source in sources.split(",") if source.strip()]

    def get_stt_keyterms(self) -> list[str]:
        """Return all configured keyterms, de-duplicated in source priority order."""
        keyterms: list[str] = []
        for source in self.get_stt_keyterm_sources():
            keyterms.extend(self._keyterms_for_source(source))
        return self._dedupe_keyterms(keyterms)

    def get_stt_keyterm_source_counts(self) -> dict[str, int]:
        """Return per-source unique keyterm counts for startup diagnostics."""
        counts: dict[str, int] = {}
        for source in self.get_stt_keyterm_sources():
            counts[source] = len(
                self._dedupe_keyterms(self._keyterms_for_source(source, warn_unknown=False))
            )
        return counts

    def get_provider_stt_keyterm_budget(self, provider: str) -> KeytermBudget:
        """Return the configured keyterm budget for ``provider``."""
        provider = provider.strip().lower()
        if provider == "elevenlabs":
            return KeytermBudget(
                max_terms=self._config.get_provider_int("elevenlabs", "max_keyterms", 900),
                max_term_chars=self._config.get_provider_int("elevenlabs", "max_keyterm_chars", 50),
            )
        if provider == "deepgram":
            return KeytermBudget(
                max_terms=self._config.get_provider_int("deepgram", "max_keyterms", 100),
            )
        if provider == "openai":
            return KeytermBudget(
                max_terms=self._config.get_provider_int("openai", "max_prompt_keyterms", 300),
                max_total_chars=self._config.get_provider_int(
                    "openai", "prompt_keyterm_char_budget", 6000
                ),
            )
        return KeytermBudget()

    def get_provider_budgeted_stt_keyterm_details(
        self,
        provider: str,
        log_result: bool = True,
    ) -> BudgetedKeyterms:
        """Return generated keyterms constrained to this provider's configured limits."""
        budget = self.get_provider_stt_keyterm_budget(provider)
        return self.get_budgeted_stt_keyterm_details(
            provider,
            max_terms=budget.max_terms,
            max_term_chars=budget.max_term_chars,
            max_total_chars=budget.max_total_chars,
            log_result=log_result,
        )

    def get_budgeted_stt_keyterms(
        self,
        provider: str,
        max_terms: int | None = None,
        max_term_chars: int | None = None,
        max_total_chars: int | None = None,
    ) -> list[str]:
        """Return generated keyterms constrained to provider-specific limits."""
        return self.get_budgeted_stt_keyterm_details(
            provider,
            max_terms=max_terms,
            max_term_chars=max_term_chars,
            max_total_chars=max_total_chars,
        ).keyterms

    def get_budgeted_stt_keyterm_details(
        self,
        provider: str,
        max_terms: int | None = None,
        max_term_chars: int | None = None,
        max_total_chars: int | None = None,
        log_result: bool = True,
    ) -> BudgetedKeyterms:
        """Return keyterm budgeting details for diagnostics and backend setup."""
        budget = KeytermBudget(
            max_terms=max_terms,
            max_term_chars=max_term_chars,
            max_total_chars=max_total_chars,
        )
        result = apply_keyterm_budget(self.get_stt_keyterms(), budget)
        if log_result and (
            result.skipped_too_long or result.omitted_by_term_limit or result.omitted_by_char_limit
        ):
            logging.info(
                "Budgeted %s STT keyterms to %s terms "
                "(skipped_too_long=%s, omitted_by_term_limit=%s, omitted_by_char_limit=%s).",
                provider,
                len(result.keyterms),
                result.skipped_too_long,
                result.omitted_by_term_limit,
                result.omitted_by_char_limit,
            )
        return result

    def _keyterms_for_source(self, source: str, warn_unknown: bool = True) -> list[str]:
        if source == "phonetic_alphabet":
            return list(PHONETIC_ALPHABET)
        if source == "fuzzy_words":
            return list(self._vocabulary.get_fuzzy_words())
        if source in ("word_mapping_replacements", "word_mappings"):
            return list(self._vocabulary.get_word_mappings().values())
        if source == "word_mapping_aliases":
            return list(self._vocabulary.get_word_mappings().keys())
        if source in ("dcs_default", "dcs_defaults"):
            return list(DEFAULT_DCS_KEYTERMS)
        if source == "vaicom":
            return load_vaicom_keyterms(self._config.app_data_location)
        if source in ("custom", "settings"):
            return [
                *self._parse_keyterm_setting("stt_keyterms"),
                *self._parse_keyterm_setting("stt_keyterms_extra"),
            ]
        if warn_unknown:
            logging.warning("Unknown stt_keyterm_sources entry '%s'.", source)
        return []

    def _parse_keyterm_setting(self, key: str) -> list[str]:
        keyterms = self._config.get_setting(key, "")
        return [keyterm.strip() for keyterm in keyterms.split(",") if keyterm.strip()]

    def _dedupe_keyterms(self, keyterms: Iterable[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for keyterm in keyterms:
            normalized_keyterm = keyterm.strip()
            if not normalized_keyterm:
                continue
            lower_keyterm = normalized_keyterm.lower()
            if lower_keyterm in seen:
                continue
            seen.add(lower_keyterm)
            deduped.append(normalized_keyterm)
        return deduped


__all__ = ["SttKeyterms"]
