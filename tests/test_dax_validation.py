
import unittest


def check_dax_structure(expression):
    """Basic structural checks, not a complete DAX parser."""

    errors = []

    if not expression.strip():
        errors.append("Empty expression")

    if expression.count("(") != expression.count(")"):
        errors.append("Unbalanced parentheses")

    if expression.count("[") != expression.count("]"):
        errors.append("Unbalanced square brackets")

    in_string = False
    i = 0

    while i < len(expression):
        if expression[i] == '"':
            # Two consecutive quotes inside a DAX string are escaped quotes.
            if in_string and i + 1 < len(expression) and expression[i + 1] == '"':
                i += 2
                continue
            in_string = not in_string
        i += 1

    if in_string:
        errors.append("Unclosed string")

    return errors


class TestDaxStructure(unittest.TestCase):

    def test_valid_measure(self):
        dax = 'Total Sales = SUM(Sales[Amount])'
        self.assertEqual(check_dax_structure(dax), [])

    def test_unbalanced_parentheses(self):
        dax = 'Total Sales = SUM(Sales[Amount]'
        self.assertIn(
            "Unbalanced parentheses",
            check_dax_structure(dax)
        )

    def test_unbalanced_brackets(self):
        dax = 'Total Sales = SUM(Sales[Amount)'
        self.assertIn(
            "Unbalanced square brackets",
            check_dax_structure(dax)
        )

    def test_unclosed_string(self):
        dax = 'Message = "Hello'
        self.assertIn(
            "Unclosed string",
            check_dax_structure(dax)
        )

    def test_empty_expression(self):
        self.assertIn(
            "Empty expression",
            check_dax_structure("")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
