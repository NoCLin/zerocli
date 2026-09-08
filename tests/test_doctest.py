"""Run the public examples embedded in zerocli's module documentation."""

import doctest
import unittest

import zerocli


class PublicDoctestPresenceTests(unittest.TestCase):
    def test_module_contains_public_examples(self):
        examples = sum(
            len(test.examples) for test in doctest.DocTestFinder().find(zerocli)
        )
        self.assertGreater(examples, 0, "zerocli's public doctest was removed")


def load_tests(loader, tests, pattern):
    tests.addTests(doctest.DocTestSuite(zerocli))
    return tests


if __name__ == "__main__":
    unittest.main()
