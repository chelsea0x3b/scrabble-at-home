# Scrabble at Home

A small self-hosted Scrabble site for 2–4 players. Python 3 + Flask, plain HTML/JS/CSS.

## Run it

```bash
pip3 install -r requirements.txt
python3 app.py                       # prompts you to set the shared password
python3 app.py --password hunter2 --port 8000
```

The server prints a local URL and a LAN URL (e.g. `http://192.168.1.20:8000`).
Anyone on your network can open the LAN URL. For family outside your home,
forward the port on your router to this computer and share your public IP.

Everyone logs in with **the shared password** plus **any name they like**. That
name is their identity: logging in with the same name on another device picks
the same seat back up.

## How to play

1. **Lobby:** lists all games. Click **New game** to make one, or click a game to join it.
2. **Waiting room:** up to 4 players join, and each player clicks **I'm ready**. Once at
   least 2 players have joined and all of them are ready, the game starts and the first
   player is picked at random.
3. **Your turn:** drag tiles onto the board, or tap a tile and then tap a square.
   - The words you'd form show up live under the rack with their points: green ✓ means
     valid and red ✗ means not in the dictionary.
   - **Shuffle** mixes your rack. **Recall** pulls placed tiles back. **Submit** plays the word.
   - Tap a placed tile to send it back. Tap two rack tiles to swap them.
   - **Exchange** lets you swap tiles with the bag (needs at least 7 tiles in the bag).
     **Pass** skips your turn.
   - When you place a blank tile, you pick which letter it stands for.

Standard rules apply: the first word covers the center star, playing all 7 tiles earns a
50-point bonus, and a word with any invalid word in it is rejected (no challenges). The
game ends when a player uses their last tile and the bag is empty, or after 6 scoreless
turns in a row. Tiles left on a rack are subtracted from that player's score.

## Dictionary

Words are checked against **TWL06** (178,691 words), bundled as `twl06.zip` and loaded at
startup. TWL06 is the 2006 North American tournament list, so a few newer words such as
OK, EW and ZE are not included.

## Data

Games are saved to `data/games.json` after every move, so restarting the server doesn't
lose games. Restarting with a different password logs everyone out.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

`tests/test_scoring.py` covers premium squares, multi-word plays, hooks, blanks and bingos,
with each expected score worked out in the comments. `tests/test_game.py` covers the
waiting room, exchanges, the end of the game and the live preview endpoint.
