"""Run the public examples embedded in zerocli's module documentation."""

import doctest
import unittest

import zerocli


def load_tests(loader, tests, pattern):
    tests.addTests(doctest.DocTestSuite(zerocli))
    return tests


if __name__ == "__main__":
    unittest.main()
