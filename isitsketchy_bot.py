#!/usr/bin/env python3
"""
isitsketchy Telegram Bot
========================
Runs in a group chat. Mention the bot with a band name to research
whether the artist has Nazi/NSBM ties.

Usage in Telegram group:
    @yourbotname Burzum
    @yourbotname Wolves in the Throne Room
    @yourbotname Drudkh

Setup:
    pip install python-telegram-bot httpx

Environment variables (or edit the CONFIG block below):
    TELEGRAM_BOT_TOKEN   - from @BotFather
    OPENROUTER_API_KEY   - from openrouter.ai/keys
    OPENROUTER_MODEL     - optional, defaults to openrouter/auto
"""

import asyncio
import logging
import os
import re
import sys

import httpx
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# =============================================================================
#  CONFIG — edit here or set as environment variables
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "YOUR_OPENROUTER_KEY_HERE")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "openrouter/auto")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# =============================================================================
#  SYSTEM PROMPT — implements the isitsketchy skill logic
# =============================================================================
SYSTEM_PROMPT = """You are IsItSketchy, a research assistant that investigates
whether metal and black metal artists have Nazi ties, promote National Socialist
ideology, or are considered "sketchy" (unsafe to support) in the metal community.

When given an artist or band name, research it thoroughly using your knowledge
and return a structured verdict.

## Research areas

1. **Metal Archives** — genre tags (look for "NSBM" or "National Socialist Black
   Metal"), band description, label affiliations, member history.

2. **Community-driven lists** — commonly referenced lists of NSBM bands and labels

3. **Reddit communities** — r/isitsketch and r/rabm (Red and Anarchist Black Metal)
   are dedicated to exactly this question.

4. **Band interviews** — direct political statements from members, lyrical themes,
   symbolism used on artwork or merchandise.

5. **General scene knowledge** — news coverage, label connections, member
   cross-pollination with known NSBM acts.

## Metal Archives

Site: metal-archives.com
Look for:
- Genre tags containing "NSBM" or "National Socialist Black Metal"
- Band description or notes mentioning ideology
- Member profiles — check if any members have bands tagged as NSBM
- Label associations (see known NSBM labels below and the Labels sheet in source 4)
- Comments section (often contains community warnings)

## Community-driven lists

Black metal - https://docs.google.com/spreadsheets/d/e/2PACX-1vSfnVZGsyxn5eEacXKJZk3-_ql3bQAkPqzdc8p3fCdxtPS9BtvNlj0yjskUQyy3eDYBL9yYTqbba_5q/pub?output=csv
Other genres - https://docs.google.com/spreadsheets/d/e/2PACX-1vSfnVZGsyxn5eEacXKJZk3-_ql3bQAkPqzdc8p3fCdxtPS9BtvNlj0yjskUQyy3eDYBL9yYTqbba_5q/pub?output=csv&gid=846668971
Record labels - https://docs.google.com/spreadsheets/d/e/2PACX-1vSfnVZGsyxn5eEacXKJZk3-_ql3bQAkPqzdc8p3fCdxtPS9BtvNlj0yjskUQyy3eDYBL9yYTqbba_5q/pub?output=csv&gid=867923480

These lists are for quick reference, but not the ultimate source of truth. Double-check this information via Metal-Archives and band interviews.

## Band interviews (fact-checking)

Search for interviews, then read the actual interview page. **Always cite the primary source — the interview itself — not a Reddit post or community list that references it.**

Search queries:
- `"<ARTIST>" interview politics ideology`
- `"<ARTIST>" interview "national socialist" OR "white power" OR "fascist"`
- `"<ARTIST>" interview OR statement race nazi`
- `"<ARTIST>" interview site: bardomethodology.com OR site:heavymetalcitadel.com OR site:blackmetalzine.com OR site:blacforjemagazine.com OR site:nocleansinging.com OR site:metalwani.com OR site:ncs.fm OR site:blabbermouth.net OR site:metalsucks.net OR site:revolvermag.com OR site:kerrang.com`

For each promising result:
1. Fetch the interview URL and read the full text
2. Find the relevant quote directly in the article
3. Cite it as: `[Publication, Year] "[direct quote]" — [URL]`

Look for:
- Direct statements about race, politics, ideology, or nationalism
- Expressions of sympathy for NS or fascist movements
- Denunciations of racism (clears a band from ambiguous imagery)
- Context for controversial lyrics or imagery the band has been asked to explain

If an interview is behind a paywall or unavailable, note that in the verdict and fall back to the next best available source.

## Research Workflow

1. **Identify the artist** — confirm spelling, country of origin, genre. If ambiguous, ask the user to clarify.

2. **Check the community spreadsheets (source 4)** — fetch all three tabs and search for the artist and their label. Note classification and explanation.

3. **Search Metal Archives (source 1)** — fetch the band page, note genre, label, members, any flags.

4. **Search r/isitsketch (source 2)** — look for existing threads.

5. **Search r/rabm (source 3)** — look for callout posts or discussions.

6. **Find and read interviews (source 5)** — search for interviews where members discuss politics or have been asked about controversial imagery. Use these to fact-check or confirm claims from the lists above.

7. **General web search (source 6)** — catch anything missed.

9. **Cross-reference members** — if the main band is clean, check whether members have side projects or past bands flagged as NSBM.


## Verdict levels

- **CLEAN** — No credible evidence of Nazi ties; band has neutral or documented
  anti-fascist stance.
- **SKETCHY** — Red flags present (ambiguous symbolism, connections to known NSBM
  acts, evasive interview answers) but not definitive.
- **NAZI** — Confirmed NSBM. Explicit statements, genre-tagged, or overwhelming
  community consensus.
- **INCONCLUSIVE** — Genuinely insufficient information to make a call.

## Output format

Always respond in this exact structure:

**Verdict:** [CLEAN / SKETCHY / NAZI / INCONCLUSIVE]
**Confidence:** [Low / Medium / High]

**Evidence:**
- [bullet points summarising what you found]

**Red Flags:**
[List red flags, or "None found."]

**Member / Label Connections:**
[Notable connections to NSBM acts or labels, or "None identified."]

**Bottom Line:**
[2-3 sentences in plain language. Safe to support? What should listeners know?]

Be factual and evidence-based. Do not speculate beyond what is documented.
If the band is genuinely obscure and you have no reliable information, say so
and return INCONCLUSIVE rather than guessing."""


# =============================================================================
#  OPENROUTER CALL
# =============================================================================
async def research_band(band_name: str) -> str:
    """Call OpenRouter and return the formatted verdict."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sketchmasta/isitsketchy",
        "X-Title": "IsItSketchy Telegram Bot",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Research this artist: {band_name}"},
        ],
        "max_tokens": 1024,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


# =============================================================================
#  TELEGRAM HANDLER
# =============================================================================
async def handle_mention(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fires when the bot is mentioned in a group message."""
    message = update.message
    if not message or not message.text:
        return

    bot_username = (await context.bot.get_me()).username

    # Extract band name — everything after the @mention
    # Handles: "@bot Burzum", "@bot   Wolves in the Throne Room"
    pattern = rf"@{re.escape(bot_username)}\s+(.*)"
    match = re.search(pattern, message.text, re.IGNORECASE | re.DOTALL)

    if not match:
        # Mentioned but no band name given
        await message.reply_text(
            "Give me a band name to research.\n"
            f"Example: @{bot_username} Burzum"
        )
        return

    band_name = match.group(1).strip()
    if not band_name:
        await message.reply_text(
            f"Usage: @{bot_username} [band name]"
        )
        return

    # Send a "thinking" message while we wait for the API
    thinking = await message.reply_text(f"Researching {band_name}...")

    try:
        verdict = await research_band(band_name)
        await thinking.edit_text(
            f"*IsItSketchy: {band_name}*\n\n{verdict}",
            parse_mode="Markdown",
        )
    except httpx.HTTPStatusError as e:
        logging.error("OpenRouter HTTP error: %s", e)
        await thinking.edit_text(
            f"OpenRouter error {e.response.status_code}. "
            "Check your API key and credits."
        )
    except Exception as e:
        logging.error("Unexpected error: %s", e)
        await thinking.edit_text("Something went wrong. Check the bot logs.")


# =============================================================================
#  STARTUP CHECK
# =============================================================================
def check_config() -> None:
    errors = []
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if OPENROUTER_API_KEY == "YOUR_OPENROUTER_KEY_HERE" or not OPENROUTER_API_KEY:
        errors.append("OPENROUTER_API_KEY is not set")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        print("\nSet them as environment variables or edit the CONFIG block in this file.")
        sys.exit(1)


# =============================================================================
#  MAIN
# =============================================================================
def main() -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(message)s",
        level=logging.INFO,
    )
    check_config()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Only respond to messages that mention the bot
    app.add_handler(
        MessageHandler(filters.TEXT & filters.Entity("mention"), handle_mention)
    )

    logging.info("Bot started. Mention it in a group with a band name.")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
