<!-- QUICKSTART.md -->
# LOWASS on Windows - quickstart

Everything below is for a Windows PC. The app is a floating window that listens to a call, checks facts and looks things up for you. Nothing is on GitHub yet, so you copy the folder by hand.

## 0. What you need (one time)

| What                                                             | Why                                                                                             | Check                  |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ---------------------- |
| Python 3.13 from python.org or the Microsoft Store               | the app. The Store version is fine and has tkinter. From python.org keep the "tcl/tk" option ON | `python --version`     |
| Your AWS profile `anycompany-ai` in `C:\Users\<you>\.aws\config` | Amazon Transcribe (speech to text). The AWS CLI is NOT needed: the app signs in by itself       | step 2                 |
| The `.env` file with 3 keys                                      | LLM, mcphub                                                                                     | step 3                 |
| A headset or speakers as the DEFAULT Windows devices             | microphone = "Ja", system audio (loopback of the default output) = "Protistrana"                | Windows Sound settings |

No compiler and no Visual Studio is needed: every package has a ready Windows wheel for Python 3.13.

## 1. Copy the project

Copy this folder to the PC, for example to `C:\lowass`:

```text
lowass\            (the python package)
lowass.toml
requirements.txt
run.bat
run-silent.bat
.env.example
README.md
```

Do NOT copy `.venv`, `data`, `memory-bank`, `.git`. They are not needed and the `.venv` from Linux does not work on Windows.

## 2. AWS profile and login

The profile `anycompany-ai` is a chained profile: it takes the role from the SSO login of the profile `anycompany-sso`. Copy these blocks from your Linux `~/.aws/config` into `C:\Users\<you>\.aws\config` (the file may not exist yet; create it) and use your own profile names and addresses:

```ini
[sso-session anycompany]
sso_start_url = https://anycompany.awsapps.com/start/#
sso_region = eu-central-1
sso_registration_scopes = sso:account:access

[profile anycompany-sso]
sso_session = anycompany
sso_account_id = <the account id of your SSO profile>
sso_role_name = TeamRole
region = eu-central-1

[profile anycompany-ai]
source_profile = anycompany-sso
role_arn = arn:aws:iam::<account id of the target account>:role/TeamRole
role_session_name = ai-session
```

Take the two account ids from your Linux config (`grep -A4 "profile anycompany-sso\]" ~/.aws/config`, same for the other profile); they are not repeated here on purpose.

Sign in: the app does it itself with a device code (like `aws sso login --use-device-code`). Nothing to install, and no password is typed into the app:

- On the first start with audio, and whenever the login has expired, a browser page opens and the window shows `AWS sign-in: approve in the browser (code XXXX-XXXX)`.
- In the AWS page you type your user name, password and MFA yourself and approve the device. The window then says `AWS sign-in done.` and the transcription works. Speech spoken before you approve is not transcribed.
- To sign in on purpose: type `/login` into the chat box, or run `run.bat --login` (no window, it only signs in and exits).
- The token is stored in `C:\Users\<you>\.aws\sso\cache` in the same format the AWS CLI uses, so the AWS CLI (if you ever install it) sees the same login. The app renews it by itself while the refresh token lives.

Check it works: start the app (step 5); the transcription lines appear after the approval.

Notes:

- The `anycompany-sso` profile alone is NOT allowed to use Transcribe (AccessDenied). Keep `profile = "anycompany-ai"` in `lowass.toml [transcribe]` (use the name of a profile that is allowed to call `transcribe:StartStreamTranscription`).
- The login lasts some hours. When it expires the app opens the sign-in page again by itself; no restart needed.
- Never put keys or role ARNs into `lowass.toml`; only the profile name.

## 3. The .env file

Copy `.env.example` to `.env` (same folder) and fill in:

```bat
LITELLM_BASE_URL=https://litellm.anycompany.example/v1
LITELLM_API_KEY=<the LiteLLM key>
MCPHUB_TOKEN=<the mcphub bearer token>
```

The keys are on your Linux machine in `~/DEVEL/lowass/.env` (copy the three values; do not send the file by plain e-mail). `GROQ_API_KEY` is needed only if you switch `stt.provider` to `"groq"`.

Then the config. `lowass.toml` is created from `lowass.toml.sample` by the first start (or copy it yourself: `copy lowass.toml.sample lowass.toml`). Open it and set at least:

- `[transcribe].profile`: the name of your AWS profile from step 2,
- `[projects.*]`: your projects, each with the address of your mcphub (`mcphub_url`) and a short prompt about the customer,
- `[hint].names`: how the others call you.

The file is local and not in git, so an update of the program never overwrites it.

## 4. First start - without audio (2 minutes)

Open a Command Prompt in the folder and run:

```bat
cd C:\lowass
run.bat --no-audio
```

The first start creates `.venv` and installs the packages (a few minutes). Then the window appears on the right edge of the screen.

What to check:

1. The window is always on top, narrow, with the buttons `Clear`, `Screen`, `Private`, `auto` and the model dropdown, a project dropdown below it, and the shortcut buttons (`Fact-check`, `Summary`, ...) above the chat box.
2. The status says `project: general` after a few seconds (the connection to mcphub works). If it says `not connected`, read the red text in the window and `lowass.log`.
3. Type a question into the box, for example `Kolik je 2+2?`, press Enter. An answer appears.
4. Try a lookup: `Najdi v Jire poslednich 3 ticketu prirazenych mne.`

## 5. Then with audio

```bat
run.bat
```

1. Right after the start the window prints `Listening. me: <your microphone> | other: <your headphones> [Loopback]`. If the names are wrong, set the right DEFAULT devices in the Windows Sound settings and restart.
2. A green line under the status shows live numbers (debug is on). Speak: `Ja rms ...` should go above the threshold and `STT ok` should grow. Grey `~ Ja: ...` lines show what was heard.
3. Play a YouTube video or join a call: the `Prot...` numbers move and `~ Protistrana: ...` lines appear.
4. After a pause of about 4 seconds the assistant reacts only if it finds something worth saying.

## 6. Everyday use

| Action                                            | How                                                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Pick the project (your own list)    | the dropdown; it starts a clean meeting                                                                                   |
| Check what was said now                           | `Fact-check` button or `Ctrl+Alt+Space`                                                                                   |
| Summary, actions, decisions of the meeting so far | the buttons above the chat box (editable in `lowass.toml`)                                                                |
| Ask the assistant by voice                        | say `Tose Samo` / `Samo Seto` / `Samo Tose` + the question                                                                |
| Freeze everything for a private moment            | `Private` button or `Ctrl+Alt+P` (red = nothing new is heard; what was running finishes)                                  |
| Foreign speech in Czech                           | `Translate` button (blue = on): the transcript window opens next to the main window; its FROM and TO dropdowns say what is translated (default German into Czech, `en-US` to `cs-CZ` for English); off = only transcribed |
| Short sentences in another language come out as nonsense | the dropdown next to the model: pick the language that is spoken (it moves to the front for the next sentence); back to `default` when the talk changes |
| Screenshot of the Teams window (primary monitor)  | `Screen` or `Ctrl+Alt+S`                                                                                                  |
| Where the window is                               | on the monitor with the HIGHEST number, as high as the monitor (`[ui].monitor`, `[ui].height = "full"` in `lowass.toml`)                                    |
| Raise the window and type                         | `Ctrl+Alt+L`                                                                                                              |
| Numbers, dates and agreements of the meeting      | the facts window opens by itself when the model finds facts; `Facts` button (row two of the toolbar) opens and closes it  |
| Suggested answer to a question put to you         | a card appears left of the window after about 12 s of your silence; click it or `Ctrl+Alt+C` copies it                    |
| End the meeting and get a summary                 | `Clear` (or switch the project)                                                                                           |
| Ask the assistant about the past                  | just ask in the box: it searches the earlier meetings itself                                                              |
| Colours                                           | red = FALSE / NEPRAVDA, green = CONFIRMED / POTVRZENO, violet = INFO, yellow = the assistant's opinion, blue = translations |

Meetings are stored in `C:\lowass\data\<project>\<session>\` (`transcript.md`, `chat.md`, `summary.md`, `facts.md`, `screens\`). The vector index is `data\memory.db`.

`run-silent.bat` starts the app without a console window; then everything is in `lowass.log`.

## 7. When something does not work

| Symptom                                                   | Cause and fix                                                                                                        |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `'py' is not recognized`, `No Python 3.11 or newer found` | `run.bat` tries `py`, `python`, `python3`; install Python 3.13 (Microsoft Store or python.org) and open a NEW window |
| `No module named tkinter`                                 | reinstall Python with the "tcl/tk and IDLE" option                                                                   |
| The browser page does not open                            | the window prints the address; copy it into a browser. Or type `/login` into the chat box                            |
| `The sign-in was not approved in time`                    | the code is valid 10 minutes; type `/login` for a new one                                                            |
| `AWS sign-in service not reachable`                       | no internet, or a proxy blocks `oidc.eu-central-1.amazonaws.com`                                                     |
| Red text: `Profile 'x' may not call transcribe`           | the profile has no Transcribe right; use `anycompany-ai`                                                             |
| Red text: `AWS profile 'ai' not found`                    | step 2: the profile is missing in `C:\Users\<you>\.aws\config`                                                       |
| `No audio from 'Ja' after 10 s`                           | wrong default microphone, or Windows Settings -> Privacy -> Microphone -> allow desktop apps                         |
| `rms` stays far below the threshold when you speak        | lower `mic_threshold` in `lowass.toml [audio]`                                                                       |
| `Prot...` never moves                                     | the loopback follows the DEFAULT output device; switch the default output and restart                                |
| `Cannot connect project`                                  | mcphub token wrong, or the VPN/network blocks your mcphub address                                                  |
| Screenshot shows the wrong monitor                        | the app takes the monitor that Windows marks as PRIMARY (Display settings -> "Make this my main display")            |

Always look at `lowass.log` next to `lowass.toml`: devices, STT results, every error with its traceback.

## 8. Not tested yet (tell me what you see)

Audio capture and loopback, the window itself, the three hotkeys, the Screen button on your monitors, the `.bat` files, and the AWS profile on Windows have only been checked on Linux. Please report the first thing that does not match this page.

Already seen working on Windows: live captions, the suggested-answer card, the transcript window with translation (en to cs and de to cs), the facts window, the window on the second monitor.

Not seen on a screen yet, please look at these first:

1. The two toolbar rows at your width (the model and project boxes grow, the language box stays on the right).
2. `height = "full"`: the window must end exactly at the taskbar. The log line `full height: frame ...` shows what was measured; send it if the window overlaps the taskbar or stops short.
3. The yellow tooltip over a shortcut button, and a yellow line when the assistant gives its opinion (only when it starts a bullet with OPINION or NAZOR).
4. The language dropdown with real speech: with German chosen, short German sentences should be recognised and translated; with the default order short German sentences may be taken for Czech (measured). Language and project always start on their default (nothing is saved between starts); only the model choice is remembered.
5. `Ctrl+Alt+C` copies the text of the card; `Ctrl+Alt+P` toggles Private.

When everything works, switch the debug off: `lowass.toml` -> `[debug]` -> `enabled = false`.
