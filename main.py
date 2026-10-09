import os
import sys
import time
import logging
import requests
from openai import OpenAI

from wings.movie_facts import SYSTEM_PROMPT as FACTS_SYSTEM, USER_PROMPT as FACTS_USER
from wings.cinema_quiz import SYSTEM_PROMPT as QUIZ_SYSTEM, USER_PROMPT as QUIZ_USER
from wings.movie_recommendations import SYSTEM_PROMPT as RECS_SYSTEM, USER_PROMPT as RECS_USER

logging.basicConfig(
level=logging.INFO,
format="%(levelname)s | %(message)s",
)

MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

WINGS = [
("movie_facts", FACTS_SYSTEM, FACTS_USER),
("cinema_quiz", QUIZ_SYSTEM, QUIZ_USER),
("movie_recommendations", RECS_SYSTEM, RECS_USER),
]

def required_env(name):
value = os.getenv(name)
if not value:
raise RuntimeError(f"Missing required GitHub Secret: {name}")
return value

def generate_content(client, system_prompt, user_prompt):
response = client.chat.completions.create(
model=MODEL,
messages=[
{"role": "system", "content": system_prompt},
{"role": "user", "content": user_prompt},
],
temperature=0.8,
max_tokens=700,
)

content = response.choices[0].message.content
if not content or not content.strip():
    raise RuntimeError("The AI returned empty content.")

return content.strip()

def send_telegram_message(bot_token, chat_id, text):
url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
payload = {
"chat_id": chat_id,
"text": text,
"disable_web_page_preview": True,
}

for attempt in range(3):
    try:
        response = requests.post(url, json=payload, timeout=30)

        if response.ok:
            data = response.json()
            if data.get("ok"):
                message_id = data.get("result", {}).get("message_id")
                logging.info("Telegram post sent; message_id=%s", message_id)
                return

        logging.error(
            "Telegram returned HTTP %s: %s",
            response.status_code,
            response.text[:500],
        )

    except requests.RequestException as exc:
        logging.error("Telegram request failed: %s", exc)

    if attempt < 2:
        time.sleep(2 * (attempt + 1))

raise RuntimeError("Failed to send the post to Telegram after 3 attempts.")

def main():
api_key = required_env("OPENROUTER_API_KEY")
bot_token = required_env("TELEGRAM_BOT_TOKEN")
chat_id = required_env("TELEGRAM_CHAT_ID")

client = OpenAI(
    api_key=api_key,
    base_url=OPENROUTER_BASE_URL,
    default_headers={
        "HTTP-Referer": "https://github.com/mad477382-prog/tele",
        "X-Title": "FilmFilesX Auto Publisher",
    },
)

selected_wing = os.getenv("WING")
if selected_wing:
    selected = [wing for wing in WINGS if wing[0] == selected_wing]
    if not selected:
        raise RuntimeError(f"Unknown WING value: {selected_wing}")
    wings_to_run = selected
else:
    # Select one content category per run.
    import random
    wings_to_run = [random.choice(WINGS)]

for wing_name, system_prompt, user_prompt in wings_to_run:
    logging.info("Generating content using wing: %s", wing_name)

    content = generate_content(client, system_prompt, user_prompt)

    logging.info("Generated content successfully (%s characters).", len(content))
    send_telegram_message(bot_token, chat_id, content)

if name == "main":
try:
main()
except Exception:
logging.exception("FilmFilesX run failed")
sys.exit(1)
