# 🐂 BULLSHIT Telegram bot

Community bot for **$BULLSHIT** ("NO UTILITY. JUST BULLSHIT."): welcome + verification,
anti-scam/anti-spam, moderation, official info. Python 3.12 · aiogram 3 · SQLite.

Hard rules baked in: no secrets in code, **no invented contract address** (shows `COMING SOON`),
no profit promises, no wallet custody, never asks for seed phrases.

## 1. Create the bot
1. @BotFather → `/newbot` → copy the token.
2. @BotFather → `/setprivacy` → **Disable** (otherwise the bot can't read group messages to moderate).
3. Add the bot to your group and make it **admin** with: delete messages, restrict/ban members, pin messages.
4. Get your numeric user ID (e.g. @userinfobot) and the group's chat ID (negative number, e.g. `-100…`).
5. If a token ever leaks (pasted in a chat, committed to git): BotFather → `/revoke`.

## 2. Configure
```bash
cp .env.example .env     # then edit; .env is git-ignored
```
Required: `BOT_TOKEN`, `OWNER_IDS`/`ADMIN_IDS`. Strongly recommended: `GROUP_ID`
(the bot ignores every other group), `LOG_CHAT_ID`.
Leave `BULLSHIT_CA` and `BUY_LINK` empty until they really exist. Invalid values stop the bot at startup.

## 3. Run
**Docker (VPS):**
```bash
docker compose up -d --build
docker compose logs -f bot
```
**Without Docker:**
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ./.env; set +a
python -m app.main
```
Needs an always-on machine. A phone (Termux) will sleep and the bot goes quiet; use a cheap VPS.
Health: the container writes a heartbeat file; `docker ps` shows `healthy`.

SQLite is enough for one community. Schema lives in `migrations/*.sql` (plain SQL) if you
later move to PostgreSQL.

## 4. Tests
```bash
python -m unittest discover -s tests -t .
```
Pure-logic tests (config, CA validation, scam scoring, spam, warnings, DB, texts, permissions)
need no Telegram. See "Known gaps" below.

## Commands
**Everyone:** `/start /help /about /rules /ca /contract /links /socials /stats /bullshit /thesis /wen /gm /gn`

**Admins** (Telegram group admins or `ADMIN_IDS`; others get "Permission denied."):
| Command | What |
|---|---|
| `/ban /unban /kick` | reply, `@username`, or user ID. `@username` only works for users the bot has seen |
| `/mute [10m\|2h\|1d] [reason]` `/unmute` | default `MUTE_MINUTES` |
| `/warn [reason]` `/warnings` `/clearwarnings` | 3 warnings = 1h mute, 5 = ban (configurable) |
| `/purge` | reply to the first message to delete (max 100) |
| `/lock` `/unlock` | freeze / restore chat permissions |
| `/lockdown` | raid mode toggle: no links/forwards/files from non-admins, stricter scam threshold |
| `/settings` | show effective settings (no secrets) |
| `/setwelcome <html>` `/setrules <html>` | `reset` restores default. Welcome vars: `{first_name} {username} {mention} {group_name}` |
| `/setthreshold <name> <n>` | `flood_messages flood_seconds repeat_limit mute_minutes warn_mute_at warn_ban_at max_links probation_hours verify_timeout_seconds` |
| `/announce <text>` | posts to `GROUP_ID` with an "OFFICIAL" header. Attach/reply to a photo for an image. Buttons: lines like `[Label\|https://url]` |

**Owner only** (`OWNER_IDS`): `/setca <address|clear>` (validated, two-step confirm, logged) and
`/setlinks <x|website|buy|telegram> <https-url|clear>`.

## What it protects against
- **Join verification:** new members are muted until they tap a button; kicked after `VERIFY_TIMEOUT_SECONDS`.
- **Probation:** for `PROBATION_HOURS` new members can't post links, forwards or files.
- **Scam scoring:** seed-phrase/key requests, wallet-connect and claim bait, "send SOL to receive",
  fake-admin claims, shorteners, lookalike domains (`pump.fun.evil.com`, `phantom-xyz.top`), hidden
  links behind text. Needs a *combination* of signals, so ordinary "wen airdrop?" chat is left alone.
  Warnings like "never share your seed phrase" are not flagged.
- **Impersonation:** names resembling an admin add to the scam score; new joiners are flagged to the log chat.
- **Spam:** flood, repeated messages, too many links; escalating mutes.
- **Raids:** `/lockdown`, `/lock`, bots added by non-admins are banned, join/leave messages are removed.
- **CA safety:** CA comes from env or an owner-only, confirmed, logged `/setca`.
  Admins never DM first: say it in the pinned message.

## Security notes
- Secrets only via environment. Logs redact the token. The DB stores no seed phrases/keys/passwords.
- The bot never holds funds and never asks users to send anything to it.
- Log chat receives every moderation action, CA/link change and announcement.
- Keep `OWNER_IDS` to as few accounts as possible and enable 2FA on them.
- Back up `data/bullshit.sqlite3` (or the `bot-data` volume) if warnings history matters.

## Known gaps
- Handlers (the aiogram layer) are thin wrappers over the tested logic but were **not run against
  real Telegram** when this was written. Do a smoke test in a private test group first (checklist below).
- `/stats` message counts only cover time since the bot started counting (UTC); member count comes from Telegram.
- Telegram bots cannot resolve arbitrary `@username`s, hence reply/ID fallback.

## Smoke test checklist (private test group)
1. Start bot, send `/about` → shows `CA: COMING SOON`.
2. Join with a second account → muted, verify button works, welcome shows.
3. Second account sends `send me your seed phrase` → deleted + warning + alert.
4. Same account posts a link → deleted (probation).
5. Spam 8 messages quickly → muted.
6. Non-admin sends `/ban` → "Permission denied."
7. Owner: `/setca <test address>` → confirm → `/ca` shows it; `/setca clear` resets.
