<img src="https://capsule-render.vercel.app/api?type=waving&height=200&color=0:202323,55:303635,100:e7ac80&text=LOWASS&fontColor=f1d6b4&fontSize=58&fontAlignY=38&desc=LOcal%20Windows%20ASSistant%20%C2%B7%20live%20call%20helper&descSize=20&descColor=f1d6b4&descAlignY=60" width="100%" alt="" />

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.13-e7ac80?style=for-the-badge&logo=python&logoColor=e7ac80&labelColor=303635)](https://www.python.org/)
[![Amazon Transcribe](https://img.shields.io/badge/Amazon-Transcribe-e7ac80?style=for-the-badge&logo=amazon-aws&logoColor=e7ac80&labelColor=303635)](https://aws.amazon.com/transcribe/)
[![Strands Agents](https://img.shields.io/badge/Strands-Agents-e7ac80?style=for-the-badge&labelColor=303635)](https://strandsagents.com/)
[![License MIT](https://img.shields.io/badge/License-MIT-e7ac80?style=for-the-badge&labelColor=303635)](LICENSE)
[![Tests](https://img.shields.io/github/actions/workflow/status/mirecekd/lowass/tests.yml?branch=main&style=for-the-badge&label=TESTS&color=e7ac80&labelColor=303635)](https://github.com/mirecekd/lowass/actions)

[![Buy Me a Beer](https://img.shields.io/badge/If%20you%20like%20my%20work%20you%20can-Buy%20Me%20a%20Beer-e7ac80?style=for-the-badge&labelColor=303635)](https://buymeacoffee.com/mirecekd)

</div>

## 🚀 What is LOWASS?

A floating always-on-top window for Windows that listens to your work conversation (microphone + system audio), transcribes it live and quietly works for you in the background: it fact-checks claims, looks things up through your mcphub, offers a suggested answer when someone asks you something, and keeps a running facts sheet of the meeting. It has a chat box and a small live-caption panel, but no transcript view.

## 🧠 How it works?

### 1. Listen
- Your microphone is "Ja", the system audio of the call (loopback) is "Protistrana".
- Amazon Transcribe streams the words while you speak (Groq Whisper is kept as a fallback). Foreign speech can be translated on demand.

### 2. Think
- A Strands agent reads the recent conversation and a rolling facts sheet, and uses your mcphub tools (Jira, Confluence, GitLab, GitHub, web, AWS docs). It is read-only: write-like tools are blocked.

### 3. Tell you quietly
- Findings appear in the window with verdict colours. A small card suggests what to answer when a question was put to you and you stay silent. Nothing steals the keyboard focus.

## ✨ Features

- Live captions, wake phrase, Private mode, Screen button, shortcut buttons (summary, actions, decisions, now).
- Suggested-answer card, rolling facts sheet, meeting memory with a summary at the end and search over past meetings.
- Czech, Slovak, English and German speech by default (in this order), more by configuration.

## 🛠️ Technology Stack

Python 3.13, tkinter, Strands Agents (via a LiteLLM proxy), Amazon Transcribe and Translate, SQLite with Cohere Embed v4 vectors, mcphub. Windows at runtime, tests run on Linux.

## ⚙️ Setup (Windows)

Short version below; the step-by-step guide with checks and troubleshooting is in `QUICKSTART.md`.

1. Install Python 3.13 (from python.org or the Microsoft Store; tkinter is included). The `py` launcher is NOT required: `run.bat` finds `py`, `python` or `python3` by itself.
2. Define your SSO profile in `%USERPROFILE%\.aws\config` (the profile named in `lowass.toml [transcribe].profile`, default `anycompany-ai`). The AWS CLI is not needed: the app signs in itself with a device code (a browser page opens, you type the password and MFA there). `/login` in the chat box or `run.bat --login` repeats it.
3. Copy `.env.example` to `.env` and fill in the keys. `lowass.toml` is created from `lowass.toml.sample` on the first start; then set your AWS profile, mcphub addresses and projects in it.
4. Run `run.bat` (first start creates `.venv` and installs requirements).

`run-silent.bat` starts it without a console window. `python -m lowass --no-audio` starts only the window and chat.

## 🧭 Use

- Auto mode: after a pause in the conversation the assistant reviews what was said and posts findings only when it has something (CONFIRMED / FALSE / UNVERIFIED / INFO, in Czech POTVRZENO / NEPRAVDA / NEOVERENO / INFO).
- `Ctrl+Alt+Space` or the Fact-check button: review the recent conversation now.
- Windows and monitors: the main window starts on the monitor with the HIGHEST number (`[ui].monitor = "last"`; `"primary"` or a number such as `2` work too) and is as HIGH as the monitor (`[ui].height = "full"`: from the top edge to the taskbar; a number of pixels works too and then `y` is the distance from the top). With a single monitor everything is simply on it, and a number that does not exist falls back to the highest one. The hint card, the transcript window, the facts window and the tooltips always stay on the monitor the main window is on. The transcript window (top) and the facts window (bottom) are stacked right next to the main window on its left, each half of the monitor's height; the hint card is short-lived, so it simply lies over them while it is shown. Drag the main window to another monitor and the next card or window opens there.
- Transcript window: the `Translate` button also opens a second small window in the TOP slot (half of the monitor's height, right next to the main window) (it never takes the keyboard focus, you can drag it; the X closes it AND turns the `Translate` button off; the button opens it again). It shows the whole running transcript of both sides, scrolls, and puts the translation of a foreign sentence under it in blue (`-> ...`). The translation is also written into the main log, so it stays readable at normal speaking speed.
- Live captions: a small panel under the status line shows what is being said while it is said (grey = still changing, white = final). The microphone and the loopback are shown separately. Foreign speech is only transcribed, unless the `Translate` button in the toolbar is on (blue): then every foreign sentence (German by default; the languages you understand are in `[translate].understood`) is translated into Czech about 0.1 s after it is final and shown under the sentence in blue. Off = Amazon Translate is never called. `[translate].on_start` sets the state at start (default off).
- Buttons under the log (`[[ui.shortcuts]]` in `lowass.toml`): `Fact-check` (same as `Ctrl+Alt+Space`), `Summary`, `Actions`, `Decisions`, `Now`. Each custom button runs its own prompt over the WHOLE meeting so far. Add, rename or remove buttons in the config.
- Wake phrase: say `Tose Samo`, `Samo Seto` or `Samo Tose` (microphone only) at the START of a sentence, also after a lead-in word (`hele Tose Samo, ...`; the words are `[wake].lead_ins`: hey, hej, hele, ty, kamo, at most two in a row), or at the END of it (`What now, Tose Samo?`), and the rest of the sentence goes to the assistant as a question, like typing it. A name in the MIDDLE of a sentence is only a mention and does nothing. A phrase that is also an ordinary word can be limited to the start with `[wake].start_only` (so `on Friday` does not wake it). A bare phrase waits for your next sentence. The phrases are in `[wake]`. A question asked while an automatic check is still running WAITS its turn (`[agent].queue_wait_sec`, 60 s) instead of being rejected; the status line says `waiting for the previous request...`. Only automatic checks and hints skip when the agent is busy.
- Private (toolbar button or `Ctrl+Alt+P`): red while on. It FREEZES the current state: nothing new is listened to, translated or stored and the assistant makes no automatic comments, but what was already running finishes and stays on screen (the sentence being said, its translation, a request that is with the model). For `[private].drain_sec` (10 s) the recognised text of that sentence is still accepted, then everything is muted. A question you type or a button you press still works (your own act).
- Hover a shortcut button: a yellow tooltip shows its whole prompt (or the short `hint = "..."` of that button in the config).
- Screen button / `Ctrl+Alt+S`: screenshot of the PRIMARY monitor (your Teams window). The assistant window hides for the moment of the grab, the picture is saved into the meeting folder and sent to the agent, which reads it and checks what it can.
- Suggested answer (`[hint]`): when the other side asks YOU something (a question, your name in any Czech form such as Miroslave / Mirku, or an opener like "could you") and you do not answer for `wait_sec` (12 s), the assistant looks at the conversation and the facts sheet and may show a small card to the LEFT of the window with one or two sentences to say. The card never takes keyboard focus, goes away by itself after `card_sec` or when you answer, and a click on it or `Ctrl+Alt+C` copies the text. The assistant may also decide there is nothing worth suggesting; then nothing shows. Silent in Private. Off with `[hint].enabled = false`.
- Facts sheet (`[facts]`): a short running sheet of numbers, dates, people, what was agreed and what is open. It is updated from the NEW part of the transcript only (every `min_new_words` words), saved as `facts.md` in the meeting folder and given to the assistant with every request. It needs `LITELLM_*` in `.env`; without them hints still work but there is no sheet.
- Facts window: when the model decides there are facts, a small window opens BY ITSELF in the BOTTOM slot (under the transcript window, the other half of the monitor's height) and the sheet is kept up to date in it, with the headings (NUMBERS, DATES, PEOPLE, AGREED, OPEN) in copper. It opens only once per meeting, so closing it with the X is respected; the `Facts` button in the toolbar opens and closes it any time. Clear and a project switch start a new meeting with an empty sheet.
- Toolbar: row one is `Clear`, `Screen`, `auto`, the model and the language dropdown; row two is `Private`, `Translate`, `Facts` and the project dropdown. The model and project dropdowns are narrow on purpose (the full name shows in the list).
- Recognition language (the dropdown next to the model): `default` keeps the order of `[transcribe].languages` (cs, sk, en, de). Pick a language and it moves to the FRONT of the list for the NEXT sentence. This matters because the order is a prior for SHORT sentences (measured on the real service): with Czech first, short German sentences were taken for Czech (0 of 6 right, garbled text); with German first, 6 of 6 were right. Long sentences are recognised correctly in any order. The price is the same in the other direction: with German forced first a short Czech sentence is taken for German, so switch back to `default` when the talk turns Czech.
- Translation FROM / TO (two dropdowns at the top of the transcript window): `default` = `[translate].from_default` into `[translate].to_default` (de-DE into cs-CZ, so only German is translated). Choose `en-US` to `cs-CZ` and English is translated and German is not. FROM also offers `any` (every language you do not understand, the old behaviour). A sentence is never translated into its own language. A sentence is translated only when the recognition LABELLED it with the FROM language, so for a short German sentence pick German in the recognition dropdown as well.
- Memory: every meeting is stored in `data/<project>/<session>/` (`transcript.md`, `chat.md`, `summary.md`, `screens/`) and embedded with Cohere Embed v4 into the local SQLite store `data/memory.db`. A meeting ends on Clear, on a project switch and on exit. When it ends a summary is written, shown in the window and stored. The agent can search the older meetings itself (tool `search_past_meetings`, current project only unless you say all).
- Clear button: wipes the window AND the assistant's context (chat history and the stored conversation), so the next request starts from a clean conversation. Audio keeps being transcribed, new speech is added from scratch.
- `Ctrl+Alt+L`: raise the window and focus the chat box.
- Language: it answers in the language of the conversation (English or Czech); any other language is translated into English.
- Model: pick it in the dropdown (list in `lowass.toml [models]`, default `global.anthropic.claude-haiku-5-5`; the list is yours to edit). The choice is remembered.
- Project: one dropdown in the second toolbar row (customer A, customer B, ...). It switches the mcphub address and the project prompt (both in `lowass.toml [projects.<key>]`) and starts with a clean context. The choice is remembered.
- Colours: answer lines starting with FALSE / NEPRAVDA are red, CONFIRMED / POTVRZENO are green, INFO is violet (looked up and sure), and the assistant's own opinion (a bullet starting with OPINION / NAZOR) is YELLOW, so a judgement is never mistaken for a verified fact. Blue is only for translations. The groups are `verdict_red`, `verdict_green`, `verdict_info`, `verdict_opinion` in `lowass.toml [ui]`; the system prompt tells the model to mark its opinion.
- Languages (speech): Czech, Slovak, English and German by default (in this order), more in `lowass.toml [transcribe].languages`. A language that is NOT in this list is not recognised: Transcribe then picks the closest listed one and writes nonsense (verified with Spanish: "Buenos diasodos la la visamos", labelled English, and no translation). Add its code (for example `"es-ES"`) and it is recognised and, with the Translate button on, translated into Czech. Nothing else has to be switched on. One dialect per language. Do not add many: in a test with six languages a short Spanish sentence was labelled Czech again, with five it was right, so list only the languages that really occur.
- Type a question in the box: it sees the recent conversation as context.

## 🔧 Configuration

- `.env`: secrets (LiteLLM, mcphub token, optional Groq key). AWS access is a profile name in `lowass.toml`, never keys or role ARNs.
- `lowass.toml`: thresholds, timings, hotkeys, window, prompts, read-only guard, `[memory]` (data folder, chunking, summary on/off), `[embeddings]` (model, dimensions). It is YOUR local file and is not in git: the first start creates it by copying `lowass.toml.sample`, which is the template that is in git. Edit `lowass.toml` (projects, mcphub addresses, AWS profile, your names for the hint card); when a new version brings a new section, compare with the sample.

The assistant is read-only: tools whose names look like writes are blocked.

## 🐞 Debug

Debug is on by default while testing (`lowass.toml [debug]`): a stats line in the window (mic level vs. threshold, segments, Whisper results, agent calls), grey `~` lines with what Whisper heard, warnings for a dead microphone, and `lowass.log` next to the config (all audio devices, per-segment STT timing, thread crashes). `python -m lowass --debug` forces it on. Set `save_wav_dir = "debug-wav"` to save the audio sent to Whisper. Turn it off with `enabled = false` when everything works.

## 🧪 Development

`pip install -r requirements-dev.txt`, then `pytest`. Live check without audio: `python scripts/smoke_live.py "question"`.

Version format `YYYYMMDD.X` (build day and the counter of that day); `python scripts/release.py` prints the next free one from the git tags.

## ☕ Support

<div align="center">

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/mirecekd) [!["PayPal.me"](https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif)](https://www.paypal.com/donate/?business=LJ5ZF7Q9KMTRW&no_recurring=0&currency_code=USD)

</div>

## 📄 License

MIT License - see the `LICENSE` file for details.

## 👤 Author

Miroslav Dvorak - mirecekd@gmail.com

<img src="https://capsule-render.vercel.app/api?type=waving&height=110&section=footer&color=0:e7ac80,55:303635,100:202323" width="100%" alt="" />
