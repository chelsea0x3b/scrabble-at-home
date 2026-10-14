"""Word validation against a Scrabble word list.

Uses NWL2023 (assets/nwl2023.zip), falling back to TWL06 (assets/twl06.zip) if it's missing.
"""

import os
import zipfile

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
NWL2023_PATH = os.path.join(ASSETS, "nwl2023.zip")
TWL06_PATH = os.path.join(ASSETS, "twl06.zip")


def default_path():
    return NWL2023_PATH if os.path.exists(NWL2023_PATH) else TWL06_PATH


class Dictionary:
    def __init__(self, path=None):
        path = path or default_path()
        self.name = os.path.splitext(os.path.basename(path))[0].upper()
        if path.endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
                text = z.read(name).decode("latin-1")
        else:
            with open(path, encoding="latin-1") as f:
                text = f.read()
        # Some lists put a definition after each word: only the first word on a line counts.
        firsts = (line.split(None, 1)[0] for line in text.splitlines() if line.strip())
        self.words = frozenset(w.upper() for w in firsts if w.isalpha())
        self.two_letter_words = sorted(w for w in self.words if len(w) == 2)

    def __len__(self):
        return len(self.words)

    def is_valid(self, word):
        return word.upper() in self.words
