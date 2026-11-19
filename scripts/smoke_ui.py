# scripts/smoke_ui.py
"""Builds the real App window (no audio), asks one question through the chat path, prints the window log, exits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lowass.app import App
from lowass.config import load

app = App(load(), audio=False)
app.start()
app.flow.ask(sys.argv[1] if len(sys.argv) > 1 else "Kolik je 2+2? Odpovez jednim slovem, bez nastroju.")
app.transcript.add("Protistrana", "Myslim ze Python 3.14 uz vysel jako stabilni verze a AWS Lambda ho podporuje.")


def finish():
    txt = app.ui.log.get("1.0", "end").strip()
    print("WINDOW LOG:\n" + txt)
    print("STATUS:", app.ui.status.cget("text"))
    app.ui.root.destroy()


app.ui.root.after(int(sys.argv[2]) * 1000 if len(sys.argv) > 2 else 25000, finish)
app.ui.run()
app.session.close()
