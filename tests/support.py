"""Values shared by several test files.

Kept in a normal module rather than in conftest.py: pytest loads conftest.py
itself, with its own rules, and its documentation advises against importing it
directly from tests.
"""

# Long enough to satisfy the server's minimum token length rule.
TOKEN = "test-token-0123456789-abcdefghijklmnopqrstuvwxyz"
