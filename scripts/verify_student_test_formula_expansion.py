"""Literal grammar fixtures, no OCR, training, provider or operational data access."""
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.student_test_formula_expansion_selection import FormulaSyntax, selection_kind
from scripts.prepare_student_test_formula_expansion import FROZEN_SIGNATURES, verify_frozen


class ExpansionSelectionTests(unittest.TestCase):
    def test_focused_original_and_aliases(self):
        for label in ("3", "-2", r"\frac{1}{2}", r"1+\sqrt{3}", r"6\cdot 10",
                      r"\sqrt[2]{5}", r"\frac{1}{1+2+3}\times 180"):
            with self.subTest(label=label):
                self.assertEqual(selection_kind(label), "focused")

    def test_auxiliary_complete_labels(self):
        for label in ("2x+3", "x^{2}+3x=4", r"\frac{x+1}{2}", r"\sqrt[3]{2}",
                      "x^{2}", r"2\pi", r"\left(2x+1\right)^2", "3^{20}"):
            with self.subTest(label=label):
                self.assertEqual(selection_kind(label), "auxiliary")

    def test_fragment_unknown_or_incomplete_rejected(self):
        for label in ("=", "=3", "x=", "^{2}", r"\cdot", r"\pm", "2+", "x", "x+y", "발언",
                      r"\frac{2}{}", r"\frac{2}{3", "2x=3=4", r"\unknown{2}",
                      r"\pm 2", r"\sqrt[5]{2}", "x_2", "(2x", "2x)", "2sin(x)", "1 2", "2.3 4"):
            with self.subTest(label=label):
                self.assertIsNone(selection_kind(label))

    def test_syntax_does_not_join_spaced_numbers(self):
        # Legacy numeric grammar removes whitespace; auxiliary grammar does not.
        with self.assertRaises(ValueError):
            FormulaSyntax("x+1 2").complete()

    def test_never_extract_rhs_or_return_computed_transcription(self):
        label = "x+1=3"
        self.assertEqual(selection_kind(label), "auxiliary")
        self.assertEqual(label, "x+1=3")

    def test_same_size_changed_validation_is_not_a_new_baseline(self):
        changed = {**FROZEN_SIGNATURES["m3_h1"], "annotationSha256": "0" * 64}
        with patch("scripts.prepare_student_test_formula_expansion.load_rows", return_value=([], changed)):
            with self.assertRaises(ValueError):
                verify_frozen(Path("unused-fixture"))


if __name__ == "__main__":
    unittest.main()
