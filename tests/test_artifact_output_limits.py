import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
from verify_iterative_artifacts import output_usage


class OutputLimitTests(unittest.TestCase):
    def test_end_newline_and_utf8_bytes_are_counted(self):
        self.assertEqual(output_usage([]), {'turn_bytes': 4, 'turn_lines': 1, 'line_bytes': 4})
        self.assertEqual(output_usage(['한']), {'turn_bytes': 8, 'turn_lines': 2, 'line_bytes': 4})

    def test_boundary_line_includes_newline(self):
        self.assertEqual(output_usage(['x' * 1023])['line_bytes'], 1024)
        self.assertEqual(output_usage(['x' * 1024])['line_bytes'], 1025)
        self.assertEqual(output_usage([''] * 4095)['turn_lines'], 4096)


if __name__ == '__main__':
    unittest.main()
