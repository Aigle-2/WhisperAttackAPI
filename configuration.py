import os
import logging
from collections.abc import Iterable

from stt_backends.keyterms import (
    BudgetedKeyterms,
    DEFAULT_DCS_KEYTERMS,
    DEFAULT_STT_KEYTERM_SOURCES,
    PHONETIC_ALPHABET,
    KeytermBudget,
    apply_keyterm_budget,
    load_vaicom_keyterms,
)
from theme import THEME_DEFAULT

class ConfigurationError(Exception):
    """
    Exception class for errors reading and writing configuration
    """

class ConfigurationWarning(Exception):
    """
    Warning class for errors reading configuration
    """

class WhisperAttackConfiguration:
    """
    A class to read and write the WhisperAttack configuration.
    Default configuration is loaded from the application directory,
    custom configuration is loaded from the AppData\\Local\\WhisperAttack
    directory and is combined with the default configuration.
    """
    def __init__(self, app_location: str, app_data_location: str):
        default_config = self.load_configuration(app_location)
        custom_config = self.load_configuration(app_data_location, False)
        self.config = default_config | custom_config

        default_word_mappings = self.load_word_mappings(app_location)
        custom_word_mappings = self.load_word_mappings(app_data_location, False)
        self.word_mappings = default_word_mappings | custom_word_mappings

        default_fuzzy_words = self.load_fuzzy_words(app_location)
        custom_fuzzy_words = self.load_fuzzy_words(app_data_location, False)
        self.fuzzy_words = [*default_fuzzy_words, *custom_fuzzy_words]

    def load_configuration(self, location: str, default = True) -> dict[str, str]:
        """
        Loads configuration settings.
        """
        logging.info("Loading %s configuration...", "default" if default else "custom")
        config = {}
        settings_file = os.path.join(location, "settings.cfg")
        if os.path.isfile(settings_file):
            try:
                with open(settings_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split('=', maxsplit=1)
                        if len(parts) == 2:
                            source, target = parts
                            config[source.strip()] = target.strip()
            except Exception as error:
                logging.error("Failed to load configuration settings from '%s': %s", settings_file, error)
                raise ConfigurationError("Failed to load configuration settings") from error
        elif default:
            logging.error("File not found: '%s'", settings_file)
            raise ConfigurationError("The configuration settings.cfg file could not be found")

        logging.info("Loaded configuration: %s", config)
        return config

    def load_word_mappings(self, location: str, default = True) -> dict[str, str]:
        """
        Loads word mappings from text files.
        """
        logging.info("Loading %s word mappings...", "default" if default else "custom")
        word_mappings = {}
        word_mappings_file = os.path.join(location, "word_mappings.txt")
        if os.path.isfile(word_mappings_file):
            try:
                with open(word_mappings_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split('=', maxsplit=1)
                        if len(parts) == 2:
                            aliases, target = parts
                            target = target.strip()
                            list(map(lambda alias: word_mappings.update({ alias: target }), aliases.split(';')))
            except Exception as error:
                logging.error("Failed to load word mappings from '%s': %s", word_mappings_file, error)
                raise ConfigurationError("Failed to load word mappings") from error
        elif default:
            logging.error("File not found: '%s'", word_mappings_file)
            raise ConfigurationError("The word_mappings.txt file could not be found.")

        logging.info("Loaded word mappings:")
        for key, value in word_mappings.items():
            logging.info("%s: %s", key, value)
        return word_mappings

    def load_fuzzy_words(self, location: str, default = True) -> list[str]:
        """
        Loads fuzzy words from text files.
        """
        logging.info("Loading %s fuzzy words...", "default" if default else "custom")
        fuzzy_words = []
        fuzzy_words_file = os.path.join(location, "fuzzy_words.txt")
        if os.path.isfile(fuzzy_words_file):
            try:
                with open(fuzzy_words_file, 'r', encoding='utf-8') as f:
                    fuzzy_words = [
                        line.strip() for line in f
                        if line.strip() and not line.strip().startswith('#')
                    ]
            except Exception as error:
                logging.error("Failed to load fuzzy words from '%s': %s", fuzzy_words_file, error)
                raise ConfigurationError("Failed to load fuzzy words from fuzzy_words.txt") from error
        elif default:
            logging.error("File not found: '%s'", fuzzy_words_file)
            raise ConfigurationError("The fuzzy_words.txt file could not found.")

        logging.info("Loaded fuzzy words: %s", fuzzy_words)
        return fuzzy_words

    def add_word_mapping(self, location: str, aliases: str, replacement: str) -> None:
        """
        Adds a new alias and replacement to the word mappings
        """
        if aliases.strip() == "":
            return None

        list(map(lambda alias: self.word_mappings.update({ alias: replacement }), aliases.split(';')))
        word_mappings_file = os.path.join(location, "word_mappings.txt")
        try:
            with open(word_mappings_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{aliases}={replacement}")
                f.close()
            logging.info("Added aliases: %s", aliases)
            logging.info("Added replacement: %s", replacement)
        except Exception as error:
            logging.error("Failed to add new word mapping to word_mappings.txt file: %s", error)
            raise ConfigurationError("Failed to add new word mapping to word_mappings.txt file") from error

    def get_configuration(self) -> dict[str, str]:
        """
        Return the full configuration
        """
        return self.config

    def get_safe_configuration(self) -> dict[str, str]:
        """
        Return configuration values with sensitive local settings redacted.
        """
        safe_config = {}
        for key, value in self.config.items():
            lower_key = key.lower()
            if lower_key.endswith("_env"):
                safe_config[key] = value
            elif "api_key" in lower_key or "secret" in lower_key or "token" in lower_key or "password" in lower_key:
                safe_config[key] = "<redacted>"
            else:
                safe_config[key] = value
        return safe_config

    def get_setting(self, key: str, default: str = "") -> str:
        """
        Returns a raw string configuration setting.
        """
        return self.config.get(key, default)

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        """
        Returns a boolean configuration setting.
        """
        value = self.config.get(key)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "y", "on")

    def get_int_setting(self, key: str, default: int) -> int:
        """
        Returns an integer configuration setting.
        """
        value = self.config.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logging.warning("Invalid integer value for '%s': %s. Using default %s.", key, value, default)
            return default

    def get_provider_setting(self, provider: str, key: str, default: str = "") -> str:
        """
        Returns a provider-specific setting, falling back to a generic stt_* setting.
        """
        return self.config.get(f"{provider}_{key}", self.config.get(f"stt_{key}", default))

    def get_provider_bool(self, provider: str, key: str, default: bool = False) -> bool:
        """
        Returns a provider-specific boolean setting.
        """
        provider_key = f"{provider}_{key}"
        if provider_key in self.config:
            return self.get_bool_setting(provider_key, default)
        return self.get_bool_setting(f"stt_{key}", default)

    def get_provider_int(self, provider: str, key: str, default: int) -> int:
        """
        Returns a provider-specific integer setting.
        """
        provider_key = f"{provider}_{key}"
        if provider_key in self.config:
            return self.get_int_setting(provider_key, default)
        return self.get_int_setting(f"stt_{key}", default)

    def get_word_mappings(self) -> dict[str, str]:
        """
        Returns the keyword mappings
        """
        return self.word_mappings

    def get_fuzzy_words(self) -> list[str]:
        """
        Returns the fuzzy words list
        """
        return self.fuzzy_words

    def get_stt_backend(self) -> str:
        """
        Returns the speech-to-text backend provider to use.
        """
        return self.config.get("stt_backend", "faster_whisper").strip().lower()

    def get_stt_language(self) -> str:
        """
        Returns the language hint used for transcription.
        """
        return self.config.get("stt_language", "en")

    def get_stt_prompt(self) -> str:
        """
        Returns an optional prompt for backends that support textual context.
        """
        return self.config.get("stt_prompt", "").strip()

    def get_stt_keyterm_sources(self) -> list[str]:
        """
        Returns the configured sources used to build provider keyterms.
        """
        sources = self.config.get("stt_keyterm_sources", ",".join(DEFAULT_STT_KEYTERM_SOURCES))
        return [source.strip().lower() for source in sources.split(",") if source.strip()]

    def get_stt_keyterms(self) -> list[str]:
        """
        Returns keyterms used by STT backends that support provider-side biasing.
        """
        keyterms: list[str] = []
        for source in self.get_stt_keyterm_sources():
            keyterms.extend(self._keyterms_for_source(source))
        return self._dedupe_keyterms(keyterms)

    def get_stt_keyterm_source_counts(self) -> dict[str, int]:
        """
        Returns per-source keyterm counts for startup diagnostics.
        """
        counts = {}
        for source in self.get_stt_keyterm_sources():
            counts[source] = len(self._dedupe_keyterms(self._keyterms_for_source(source, warn_unknown=False)))
        return counts

    def get_provider_stt_keyterm_budget(self, provider: str) -> KeytermBudget:
        """
        Returns the configured keyterm budget for a provider.
        """
        provider = provider.strip().lower()
        if provider == "elevenlabs":
            return KeytermBudget(
                max_terms=self.get_provider_int("elevenlabs", "max_keyterms", 900),
                max_term_chars=self.get_provider_int("elevenlabs", "max_keyterm_chars", 50),
            )
        if provider == "deepgram":
            return KeytermBudget(
                max_terms=self.get_provider_int("deepgram", "max_keyterms", 100),
            )
        if provider == "openai":
            return KeytermBudget(
                max_terms=self.get_provider_int("openai", "max_prompt_keyterms", 300),
                max_total_chars=self.get_provider_int("openai", "prompt_keyterm_char_budget", 6000),
            )
        return KeytermBudget()

    def get_provider_budgeted_stt_keyterm_details(
        self,
        provider: str,
        log_result: bool = True,
    ) -> BudgetedKeyterms:
        """
        Returns generated keyterms constrained to this provider's configured limits.
        """
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
        """
        Returns generated keyterms constrained to provider-specific limits.
        """
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
        """
        Returns keyterm budgeting details for diagnostics and backend setup.
        """
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
            return PHONETIC_ALPHABET
        if source == "fuzzy_words":
            return self.fuzzy_words
        if source in ("word_mapping_replacements", "word_mappings"):
            return list(self.word_mappings.values())
        if source == "word_mapping_aliases":
            return list(self.word_mappings.keys())
        if source in ("dcs_default", "dcs_defaults"):
            return DEFAULT_DCS_KEYTERMS
        if source == "vaicom":
            return load_vaicom_keyterms()
        if source in ("custom", "settings"):
            return [
                *self._parse_keyterm_setting("stt_keyterms"),
                *self._parse_keyterm_setting("stt_keyterms_extra"),
            ]
        if warn_unknown:
            logging.warning("Unknown stt_keyterm_sources entry '%s'.", source)
        return []

    def _parse_keyterm_setting(self, key: str) -> list[str]:
        keyterms = self.config.get(key, "")
        return [keyterm.strip() for keyterm in keyterms.split(",") if keyterm.strip()]

    def _dedupe_keyterms(self, keyterms: Iterable[str]) -> list[str]:
        deduped = []
        seen = set()
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

    def get_stt_timeout_seconds(self) -> int:
        """
        Returns the timeout for API-backed transcription requests.
        """
        return self.get_int_setting("stt_timeout_seconds", 30)

    def get_whisper_model(self) -> str:
        """
        Returns the Whisper model to use for speech-to-text
        """
        return self.config.get("whisper_model", "small.en")

    def get_whisper_device(self) -> str:
        """
        Returns the device to use for processing speech-to-text
        GPU or CPU, defaults to GPU
        """
        return self.config.get("whisper_device", "GPU")
    
    def get_whisper_compute_type(self) -> str:
        """
        Returns the compute type to be used when loading the Whisper model
        auto, default, or specific value, e.g. int8_float16, defaults to "default"
        which for Whisper models is float16
        https://opennmt.net/CTranslate2/quantization.html#quantize-on-model-loading
        """
        return self.config.get("whisper_compute_type", "default")

    def get_whisper_core_type(self) -> str:
        """
        Returns type of GPU cores used for the compute type for processing
        Tensor Cores are available on devices with compute capability 7.0 or higher
        tensor or standard, defaults to tensor
        """
        return self.config.get("whisper_core_type", "tensor")

    def get_theme(self) -> str:
        """
        Returns the name of the theme to be used when displaying
        UI elements. When the configuration is set to "default" then
        the name returned will be the current Windows theme.
        """
        return self.config.get("theme", THEME_DEFAULT)
    
    def get_voiceattack_host(self) -> str:
        """
        Returns the IP address of the machine running VoiceAttack.
        Used for sending the transcribed text to the VoiceAttack plugin.
        Default is 127.0.0.1 (the ip address for localhost).
        """
        return self.config.get("voiceattack_host", "127.0.0.1")
    
    def get_voiceattack_port(self) -> int:
        """
        Returns the port number to connect to for VoiceAttack.
        Used for sending the transcribed text to the VoiceAttack plugin.
        Default is 65433.
        """
        voiceattack_port = self.config.get("voiceattack_port", 65433)
        return int(voiceattack_port)
    
    def get_text_line_length(self) -> int:
        """
        Returns the line length for wrapping text. Used for sending text
        to the DCS kneeboard notes.
        Default is 53 characters.
        """
        line_length = self.config.get("text_line_length", 53)
        return int(line_length)
