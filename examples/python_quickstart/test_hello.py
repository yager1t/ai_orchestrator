import unittest

from hello import greet


class TestHello(unittest.TestCase):
    def test_greet_default(self) -> None:
        self.assertEqual(greet(), "Hello, world!")

    def test_greet_name(self) -> None:
        self.assertEqual(greet("ai-orch"), "Hello, ai-orch!")


if __name__ == "__main__":
    unittest.main()
