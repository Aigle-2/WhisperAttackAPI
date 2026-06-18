import unittest

from transcription_postprocess import compact_spelled_codes


class TranscriptionPostprocessTests(unittest.TestCase):
    def test_compacts_spaced_letter_codes(self):
        text = compact_spelled_codes("request U L M B weather and I F F")

        self.assertEqual(text, "request ULMB weather and IFF")

    def test_compacts_hyphenated_and_dotted_letter_codes(self):
        text = compact_spelled_codes("tune U-L-M-B then E.S.N.J and T-V")

        self.assertEqual(text, "tune ULMB then ESNJ and TV")

    def test_leaves_long_letter_runs_uncompacted(self):
        text = compact_spelled_codes("A B C D E F G")

        self.assertEqual(text, "A B C D E F G")


if __name__ == "__main__":
    unittest.main()
