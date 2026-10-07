"""Word validation using the TWL06 Scrabble word list (bundled as twl06.zip)."""

import os
import zipfile

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets/twl06.zip")


class Dictionary:
    def __init__(self, path=DEFAULT_PATH):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            text = z.read(name).decode("latin-1")
        self.words = frozenset(w.upper() for w in text.split() if w.isalpha())
        self.two_letter_words = sorted(w for w in self.words if len(w) == 2)

    def __len__(self):
        return len(self.words)

    def is_valid(self, word):
        return word.upper() in self.words
