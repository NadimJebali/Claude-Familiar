"""Standalone visual test for the speech bubble — no widget/restart needed.

    python test_bubble.py

Opens a small window in the center of the screen and shows the bubble cycling
through a few messages, then closes itself after ~16s. If you can see the
bubble here, the bubble rendering works; if the real widget still doesn't show
it, restart `python run_mascot.py` so it picks up the latest code.
"""
from __future__ import annotations

import tkinter as tk

from mascot.tkinter_app import BubbleWindow, CARD_WIDTH, CARD_HEIGHT, CARD_BG

MESSAGES = [
    "Claude needs your permission to use Bash",
    "Claude needs your permission to use Write",
    "Claude is waiting for your input",
]


def main() -> None:
    root = tk.Tk()
    root.title("Bubble test")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()

    # A fake mascot card in the center, so the bubble has something to sit above.
    card_x, card_y = sw // 2 - CARD_WIDTH // 2, sh // 2
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=CARD_BG)
    root.geometry(f"{CARD_WIDTH}x{CARD_HEIGHT}+{card_x}+{card_y}")
    tk.Label(root, text="⏳", font=("Segoe UI Emoji", 40), bg=CARD_BG, fg="#fff").pack(pady=20)
    tk.Label(root, text="bubble-test", font=("Arial", 8), bg=CARD_BG, fg="#ebebeb").pack()

    bubble = BubbleWindow(root, MESSAGES[0])
    bubble.place_above(card_x, card_y, CARD_WIDTH, sw)

    def step(i: int) -> None:
        if i >= len(MESSAGES):
            print("Done.")
            root.destroy()
            return
        print(f"Showing: {MESSAGES[i]!r}")
        bubble.set_message(MESSAGES[i])
        bubble.place_above(card_x, card_y, CARD_WIDTH, sw)
        root.after(4000, step, i + 1)

    print("A fake mascot + bubble should appear in the center of your screen.")
    root.after(0, step, 0)
    root.after(16000, root.destroy)  # safety auto-close
    root.mainloop()


if __name__ == "__main__":
    main()
