import unittest

from app.services.chunking import split_text


class SplitTextTests(unittest.TestCase):
    def test_short_text_stays_in_one_chunk(self):
        self.assertEqual(split_text("짧은 회의록입니다."), ["짧은 회의록입니다."])

    def test_long_text_respects_maximum_size(self):
        chunks = split_text("가" * 2000)
        self.assertEqual([len(chunk) for chunk in chunks], [800, 800, 700])
        self.assertTrue(all(len(chunk) <= 800 for chunk in chunks))

    def test_empty_text_returns_no_chunks(self):
        self.assertEqual(split_text("   \n\n"), [])

    def test_invalid_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            split_text("회의록", max_chars=100, overlap_chars=100)


if __name__ == "__main__":
    unittest.main()
