# Claude Usage Widget

A tiny always-on-top desktop widget for Windows that shows, in real time, how
much of each Claude account's limits you've used — so you can pace your
**session (5-hour)** and **weekly (7-day)** usage and switch between accounts
before you hit a wall.

![preview](preview.png)

For every configured account it shows:

- **SESSION** — 5-hour limit usage + time until reset
- **WEEKLY** — 7-day limit usage + time until reset
- the account e-mail and the CLI label (e.g. `claude`, `claude1`) it maps to

The row of buttons at the bottom lists your **most-recent projects** across all
accounts. Click one to open a new terminal in that folder and launch the
matching Claude CLI right there.

## Compact mode

Click **－** in the title bar to collapse the widget into a tiny panel showing
just a **session-usage ring per account** — one ring for each configured
account, filled to its current 5-hour utilization and colour-coded the same way
as the full bars (green → yellow → red), with the account's accent colour
labelling it underneath.

![collapsed preview](preview-collapsed.png)

Hover a ring for the full session **and** weekly breakdown, then click **□** (or
double-click a ring) to expand back to the full view. The widget remembers which
mode it was in across restarts.

> **Privacy:** everything runs locally. The widget talks only to Anthropic's
> own API (the same endpoints Claude Code uses) with your existing local login.
> No e-mails, tokens, or usage data are sent anywhere else, and nothing personal
> is stored in this repository — your `config.json` is created locally on first
> run and is git-ignored.

---

## Requirements

- Windows
- **Python 3.11+** (only the standard library — `tkinter` + `urllib`, no `pip install` needed)
- [Claude Code](https://claude.com/claude-code) installed and logged in at least once

## Install & run

```powershell
git clone https://github.com/PanLipton/claude-usage-widget.git
cd claude-usage-widget
```

Then double-click **`Start Widget.vbs`** (launches with no console window).

Alternatives:

- **`Start Widget.bat`**, or
- directly: `pythonw claude_usage_widget.pyw`

On first run the widget copies `config.example.json` → `config.json` (a single
account pointing at the default `%USERPROFILE%\.claude`). Edit that file, or use
the **➕** button in the widget, to add your own accounts.

## Window controls

- **Drag** — grab anywhere on the panel and move it.
- **➕** — add an account (opens a small inline form).
- **⚙** — settings: choose globally whether a project button opens **Claude CLI**
  (a terminal) or **Claude Desktop** (the app). See
  [Opening projects in Claude Desktop](#opening-projects-in-claude-desktop).
- **－ / □** — collapse to the [compact ring view](#compact-mode) / restore the
  full layout.
- **◉** — pin on top. Green = always-on-top (default), grey = off.
- **✕** — close. The window position is remembered in `widget_state.json`.
- **✕ next to an account** — remove that account (appears only when you have
  more than one; never removes your last account). This only edits the widget's
  config — your actual Claude login is untouched.

Hover an e-mail / CLI label to see which config directory the account uses and
how to re-authorize it. The coloured dot next to each project shows which
account it belongs to; **right-click a project** to open it with a different
account.

---

## Configuration — `config.json`

```json
{
  "poll_seconds": 180,
  "accounts": [
    { "label": "claude",  "config_dir": "%USERPROFILE%\\.claude" },
    { "label": "claude1", "config_dir": "%USERPROFILE%\\.claude-account1" },
    { "label": "claude2", "config_dir": "%USERPROFILE%\\.claude-account2" }
  ]
}
```

| Key | Meaning |
|---|---|
| `poll_seconds` | How often to poll the usage API (minimum 15s). The reset countdowns tick every second locally regardless. |
| `accounts[].label` | The name shown on the column **and** the CLI command used to open projects (see below). For one account, `claude` is fine. |
| `accounts[].config_dir` | The Claude config directory for that account. Supports environment variables like `%USERPROFILE%`. |

You can add or remove accounts with the **➕ / ✕** buttons in the widget (which
write this file for you), or edit it by hand. The window resizes itself to fit.

> Don't have time to learn the internals? Open this folder in **Claude Code**
> and ask it: *"set me up with two Claude accounts and configure this widget for
> both."* The next section is exactly what it (or you) needs to do.

---

## Running several Claude accounts on one computer

Claude Code decides which login to use from the **`CLAUDE_CONFIG_DIR`**
environment variable (it defaults to `%USERPROFILE%\.claude`). To keep two or
more separate logins side by side, you give each one its own config directory
and a tiny wrapper command that points `CLAUDE_CONFIG_DIR` at it.

### 1. Create a launcher per account

Make a folder for small scripts and put it on your `PATH` — e.g.
`%USERPROFILE%\.local\bin`:

```powershell
$bin = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force $bin | Out-Null

# claude1 -> %USERPROFILE%\.claude-account1
@"
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-account1"
claude %*
"@ | Set-Content -Encoding ascii "$bin\claude1.bat"

# claude2 -> %USERPROFILE%\.claude-account2
@"
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-account2"
claude %*
"@ | Set-Content -Encoding ascii "$bin\claude2.bat"
```

Add the folder to your `PATH` once (new terminals will pick it up):

```powershell
setx PATH "$env:PATH;$env:USERPROFILE\.local\bin"
```

> The widget opens projects by running `<label>.bat` from
> `%USERPROFILE%\.local\bin`, so the launcher name must match the account
> `label` in `config.json` (`claude1` → `claude1.bat`). If no matching `.bat`
> exists it falls back to running the bare command (`claude`).

### 2. Log in to each account

Open a **new** terminal so the updated `PATH` is active, then:

```powershell
claude1      # then type /login  and sign in with your first account
claude2      # then type /login  and sign in with your second account
```

Each `/login` writes credentials into that account's own config directory
(`.claude-account1`, `.claude-account2`, …), so the two never collide.

### 3. Point the widget at them

Add an account in the widget with the **➕** button (or edit `config.json`):
set **Label** to `claude1` and **Config dir** to
`%USERPROFILE%\.claude-account1`, and likewise for `claude2`. The columns appear
immediately.

### Re-authorizing later

If an account shows `no credentials` or an auth error, just run its command
(`claude1`) in a terminal and `/login` again — or click any project button for
that account, which opens a terminal running its CLI.

---

## Opening projects in Claude Desktop

By default a project button opens a **terminal** and runs that account's Claude
CLI. Open **Settings (⚙)** to flip a single global switch so project buttons open
the **Claude Desktop** app for that account instead:

- **Claude CLI** — a console running `claudeN.bat` (the default).
- **Claude Desktop** — the desktop app, one window per account.

(The switch is global, not per-account; it's saved as `launch_mode` in
`config.json`. In Desktop mode the project *path* isn't used — Desktop has no
working-directory argument — so a click just brings up that account's app.)

### Why Desktop needs extra setup (and the CLI doesn't)

Claude Code (CLI) picks its login from `CLAUDE_CONFIG_DIR`, so two accounts are
just two config dirs. **Claude Desktop has no such switch.** On Windows it ships
as an **MSIX/Store package**: its login lives in one isolated per-package store,
the packaged binary refuses a second launch, and it is single-instance — so you
can't simply "run it twice" for two accounts.

The one isolation knob Desktop *does* support is Electron's `--user-data-dir`,
but that only works on a binary you launch directly, which the MSIX container
blocks. The workaround is to copy the Desktop payload out to a normal folder (a
"loose" build) and launch **that** with its own `--user-data-dir`. Your primary
account keeps using the normal Store app; each extra account runs from the loose
copy with a separate profile — **side by side, both logged in at once.**

### Set up a second Desktop account

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_desktop_account.ps1
```

The script finds your installed Claude Desktop, copies its payload to
`%LOCALAPPDATA%\ClaudeDesktopStandalone`, creates a fresh profile directory
(`%USERPROFILE%\.claude-desktop-account2` by default), prints a `config.json`
snippet, and opens the loose copy so you can **sign in with your second account**.
It runs at the same time as your main Desktop without logging it out.

Then point the widget at it in `config.json`:

```json
{
  "launch_mode": "cli",
  "desktop": {
    "aumid": "Claude_pzs8sxrjxfjjc!Claude",
    "standalone_exe": "%LOCALAPPDATA%\\ClaudeDesktopStandalone\\app\\Claude.exe"
  },
  "accounts": [
    { "label": "claude1", "config_dir": "%USERPROFILE%\\.claude-account1", "desktop": "store" },
    { "label": "claude2", "config_dir": "%USERPROFILE%\\.claude-account2",
      "desktop": { "data_dir": "%USERPROFILE%\\.claude-desktop-account2" } }
  ]
}
```

| Key | Meaning |
|---|---|
| `launch_mode` | Global launch target: `"cli"` (terminal, default) or `"desktop"`. Toggle it in **Settings (⚙)**. |
| `desktop.aumid` | The Store app's launch ID, used for any account marked `"desktop": "store"`. Stable across updates. |
| `desktop.standalone_exe` | The loose copy's `Claude.exe`, used for accounts that have a `data_dir`. |
| `accounts[].desktop` | Per account: `"store"` (the installed Store app) **or** `{ "data_dir": "…" }` (a standalone profile). Omit it and the first account defaults to `"store"`, the rest to their own standalone profile. |

### Limitations

- The loose copy is **frozen at the version you copied** — it won't auto-update.
  Re-run `setup_desktop_account.ps1` after Claude Desktop updates to refresh it.
- Sign-in happens in the second window's own flow. If your browser's callback
  focuses your *primary* Desktop instead, complete the login from inside the
  second window.
- This only changes how the widget *launches* Desktop; the usage numbers still
  come from each account's CLI credentials, exactly as before.

---

## How it works

Data comes from the same OAuth endpoints Claude Code itself uses:

| Purpose | Request |
|---|---|
| Limit usage | `GET https://api.anthropic.com/api/oauth/usage` |
| Account e-mail | `GET https://api.anthropic.com/api/oauth/profile` |
| Token refresh | `POST https://console.anthropic.com/v1/oauth/token` |

Access tokens are read from each account's `<config_dir>\.credentials.json`.
When a token is about to expire (they live ~8h) the widget refreshes it and
**writes it back** to the same file, so Claude Code and the widget stay in sync.

> ⚠️ The token endpoint sits behind Cloudflare and rejects requests without a
> `User-Agent` header, so the widget sends a `claude-cli/...` UA. The usage
> endpoint is rate-limited per account, so polling defaults to 180s (15s
> minimum) with per-account exponential backoff that backs off up to 10 minutes
> on repeated failures. The reset countdowns still tick every second locally.

### Files the widget writes (all local, all git-ignored)

| File | Contents |
|---|---|
| `config.json` | Your accounts and settings (seeded from `config.example.json` on first run). |
| `widget_state.json` | Window position and whether you left it collapsed or expanded. |
| `widget_usage.json` | The latest session/weekly numbers and e-mail for every account, atomically rewritten on each poll. Other local tools can read this to show your limits **without** spending their own rate-limited API calls. |

## Autostart with Windows (optional)

Press `Win+R`, type `shell:startup`, and drop a shortcut to **`Start Widget.vbs`**
into that folder.

## License

[MIT](LICENSE).

---
---

# Claude Usage Widget — Українською

Мінімалістичний desktop-віджет для Windows, що в реальному часі показує
використання лімітів ваших Claude-акаунтів — щоб рівномірно витрачати
**сесійний (5-годинний)** і **тижневий (7-денний)** ліміти й вчасно перемикатися
між акаунтами.

Для кожного акаунта:

- **SESSION** — використання 5-годинного ліміту + час до ресету
- **WEEKLY** — використання 7-денного ліміту + час до ресету
- e-mail акаунта та мітка CLI (`claude`, `claude1`, …)

Кнопки знизу — **останні проєкти** по всіх акаунтах: клік відкриває новий
термінал у теці проєкту й запускає відповідний Claude CLI.

## Компактний режим

Кнопка **－** у заголовку згортає віджет у маленьку панель, де лишаються тільки
**кільця сесійного навантаження** — по одному кільцю на кожен акаунт. Кільце
заповнюється відповідно до поточного 5-годинного ліміту й має той самий колір,
що й повні смуги (зелений → жовтий → червоний), а під ним — акцентний колір
акаунта.

![компактний режим](preview-collapsed.png)

Наведіть на кільце, щоб побачити повну сесійну **й** тижневу інформацію, а тоді
натисніть **□** (або подвійний клік по кільцю), щоб розгорнути назад. Віджет
запам'ятовує обраний режим між запусками.

> **Приватність:** усе працює локально. Віджет звертається лише до API Anthropic
> (ті самі ендпоінти, що й Claude Code) із вашим локальним логіном. Жодні дані
> нікуди більше не передаються; у репозиторії немає особистих даних — ваш
> `config.json` створюється локально під час першого запуску і не потрапляє в git.

## Вимоги

- Windows, **Python 3.11+** (лише стандартна бібліотека — нічого встановлювати)
- Встановлений Claude Code, у який ви хоча б раз увійшли

## Запуск

Подвійний клік на **`Start Widget.vbs`** (без вікна консолі). Альтернативи —
`Start Widget.bat` або `pythonw claude_usage_widget.pyw`. Під час першого запуску
`config.example.json` копіюється у `config.json` (один акаунт на
`%USERPROFILE%\.claude`).

## Керування вікном

- **Перетягування** — затисніть будь-де на панелі.
- **➕** — додати акаунт (невелика форма прямо у віджеті).
- **⚙** — налаштування: глобально обрати, що відкриває кнопка проєкту —
  **Claude CLI** (термінал) чи **Claude Desktop** (застосунок). Див.
  [Відкривати проєкти в Claude Desktop](#відкривати-проєкти-в-claude-desktop).
- **－ / □** — згорнути у [компактний режим з кільцями](#компактний-режим) /
  розгорнути назад.
- **◉** — закріпити поверх вікон (зелений = увімкнено, сірий = вимкнено).
- **✕** — закрити (позиція запам'ятовується).
- **✕ біля акаунта** — прибрати акаунт (з'являється лише коли акаунтів більше
  одного; останній не видаляється). Це міняє лише конфіг віджета — ваш логін
  Claude не чіпається.

Наведіть на e-mail чи мітку — побачите, який каталог використовує акаунт і як
переавторизуватись. Якщо акаунт **лише один**, підказка над проєктами не
показується (нема між чим обирати). Правий клік на проєкті — відкрити іншим
акаунтом.

## Налаштування — `config.json`

```json
{
  "poll_seconds": 180,
  "accounts": [
    { "label": "claude", "config_dir": "%USERPROFILE%\\.claude" }
  ]
}
```

- `poll_seconds` — період опитування API (мінімум 15с); лічильники до ресету
  оновлюються щосекунди локально.
- `label` — назва колонки **і** CLI-команда для відкриття проєктів.
- `config_dir` — каталог конфігурації акаунта (підтримує `%USERPROFILE%`).

Додавати/видаляти акаунти можна кнопками **➕ / ✕** у віджеті або вручну.

> Не хочете розбиратись? Відкрийте цю теку в **Claude Code** і попросіть:
> *«налаштуй мені два Claude-акаунти і цей віджет для обох»*. Нижче — саме те, що
> для цього потрібно.

## Кілька Claude-акаунтів на одному комп'ютері

Claude Code обирає логін за змінною середовища **`CLAUDE_CONFIG_DIR`** (типово
`%USERPROFILE%\.claude`). Щоб мати кілька окремих логінів, кожному дають свій
каталог і маленький скрипт-обгортку, що задає `CLAUDE_CONFIG_DIR`.

**1. Створіть лаунчер на кожен акаунт** у теці, що є в `PATH` (напр.
`%USERPROFILE%\.local\bin`):

```powershell
$bin = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force $bin | Out-Null

@"
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-account1"
claude %*
"@ | Set-Content -Encoding ascii "$bin\claude1.bat"

@"
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.claude-account2"
claude %*
"@ | Set-Content -Encoding ascii "$bin\claude2.bat"

setx PATH "$env:PATH;$env:USERPROFILE\.local\bin"
```

> Віджет відкриває проєкти, запускаючи `<label>.bat` з
> `%USERPROFILE%\.local\bin`, тож ім'я лаунчера має збігатися з `label` у
> `config.json` (`claude1` → `claude1.bat`).

**2. Увійдіть у кожен акаунт** (у новому терміналі, щоб підхопився `PATH`):

```powershell
claude1      # далі /login — вхід першим акаунтом
claude2      # далі /login — вхід другим акаунтом
```

**3. Додайте акаунти у віджет** кнопкою **➕**: `claude1` →
`%USERPROFILE%\.claude-account1`, `claude2` → `%USERPROFILE%\.claude-account2`.

**Переавторизація:** якщо акаунт показує `no credentials` — запустіть його
команду (`claude1`) і знову `/login`, або клацніть будь-який його проєкт.

## Відкривати проєкти в Claude Desktop

Типово кнопка проєкту відкриває **термінал** і запускає Claude CLI акаунта. У
**Налаштуваннях (⚙)** можна одним глобальним перемикачем змусити кнопки натомість
відкривати застосунок **Claude Desktop** для цього акаунта:

- **Claude CLI** — консоль із `claudeN.bat` (типово).
- **Claude Desktop** — десктоп-застосунок, по вікну на акаунт.

(Перемикач глобальний, не на кожен акаунт; зберігається як `launch_mode` у
`config.json`. У режимі Desktop *шлях* проєкту не використовується — у Desktop
немає аргументу робочої теки — тож клік просто відкриває застосунок акаунта.)

### Чому Desktop потребує додаткового налаштування (а CLI — ні)

Claude Code (CLI) обирає логін за `CLAUDE_CONFIG_DIR`, тож два акаунти — це просто
два каталоги. **У Claude Desktop такого перемикача немає.** На Windows він
постачається як **MSIX/Store-пакет**: логін лежить в ізольованому сховищі пакета,
бінарник не дає запустити себе вдруге, і застосунок single-instance — тож просто
«запустити двічі» для двох акаунтів не вийде.

Єдиний механізм ізоляції, який Desktop *підтримує*, — це Electron-флаг
`--user-data-dir`, але він діє лише на бінарник, який ви запускаєте напряму, а
контейнер MSIX це блокує. Обхід: скопіювати payload Desktop у звичайну теку
(«loose»-білд) і запускати **його** з власним `--user-data-dir`. Основний акаунт
далі користується звичайним Store-застосунком; кожен додатковий — loose-копією з
окремим профілем, **паралельно, обидва залогінені одночасно.**

### Налаштувати другий акаунт Desktop

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_desktop_account.ps1
```

Скрипт знаходить встановлений Claude Desktop, копіює payload у
`%LOCALAPPDATA%\ClaudeDesktopStandalone`, створює свіжий профіль
(`%USERPROFILE%\.claude-desktop-account2` за замовчуванням), друкує фрагмент для
`config.json` і відкриває loose-копію, щоб ви **увійшли другим акаунтом**. Вона
працює одночасно з основним Desktop, не розлогінюючи його.

Далі вкажіть це віджету в `config.json`:

```json
{
  "launch_mode": "cli",
  "desktop": {
    "aumid": "Claude_pzs8sxrjxfjjc!Claude",
    "standalone_exe": "%LOCALAPPDATA%\\ClaudeDesktopStandalone\\app\\Claude.exe"
  },
  "accounts": [
    { "label": "claude1", "config_dir": "%USERPROFILE%\\.claude-account1", "desktop": "store" },
    { "label": "claude2", "config_dir": "%USERPROFILE%\\.claude-account2",
      "desktop": { "data_dir": "%USERPROFILE%\\.claude-desktop-account2" } }
  ]
}
```

- `launch_mode` — глобальна ціль запуску: `"cli"` (термінал, типово) або
  `"desktop"`. Перемикається в **Налаштуваннях (⚙)**.
- `desktop.aumid` — ID запуску Store-застосунку для акаунтів із `"desktop": "store"`
  (стабільний між оновленнями).
- `desktop.standalone_exe` — `Claude.exe` loose-копії для акаунтів із `data_dir`.
- `accounts[].desktop` — на акаунт: `"store"` (встановлений Store-застосунок) **або**
  `{ "data_dir": "…" }` (окремий профіль). Якщо не вказати — перший акаунт типово
  `"store"`, решта — власний standalone-профіль.

### Обмеження

- Loose-копія **заморожена на скопійованій версії** — сама не оновлюється. Після
  оновлення Claude Desktop перезапустіть `setup_desktop_account.ps1`, щоб її освіжити.
- Вхід відбувається у власному вікні другого застосунку. Якщо колбек браузера
  фокусує *основний* Desktop — завершіть вхід усередині другого вікна.
- Це міняє лише те, як віджет *запускає* Desktop; цифри використання так само
  беруться з CLI-кредів кожного акаунта, як і раніше.

## Як це працює

Дані беруться з тих самих OAuth-ендпоінтів, що використовує Claude Code
(`/api/oauth/usage`, `/api/oauth/profile`, `/v1/oauth/token`). Токени читаються з
`<config_dir>\.credentials.json` і автоматично оновлюються та **записуються
назад**, тож Claude Code і віджет лишаються синхронізованими. Опитування типово
кожні 180с (мінімум 15с), із покроковим backoff на акаунт до 10 хвилин у разі
повторних помилок; лічильники до ресету оновлюються щосекунди локально.

### Файли, які створює віджет (усі локальні, усі в `.gitignore`)

| Файл | Що містить |
|---|---|
| `config.json` | Ваші акаунти й налаштування (на першому запуску — з `config.example.json`). |
| `widget_state.json` | Позиція вікна та стан згорнуто/розгорнуто. |
| `widget_usage.json` | Свіжі цифри session/weekly та e-mail кожного акаунта, атомарно перезаписуються при кожному опитуванні. Інші локальні інструменти можуть читати цей файл, щоб показувати ваші ліміти, **не** витрачаючи власні запити до API. |

## Автозапуск із Windows

`Win+R` → `shell:startup` → покладіть туди ярлик на **`Start Widget.vbs`**.

## Ліцензія

[MIT](LICENSE).
