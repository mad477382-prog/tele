
import os
import sys
import time
import logging
import random
import requests
from openai import OpenAI

from wings.movie_facts import (
    SYSTEM_PROMPT as FACTS_SYSTEM,
    USER_PROMPT as FACTS_USER,
)
from wings.cinema_quiz import (
    SYSTEM_PROMPT as QUIZ_SYSTEM,
    USER_PROMPT as QUIZ_USER,
)
from wings.movie_recommendations import (
    SYSTEM_PROMPT as RECS_SYSTEM,
    USER_PROMPT as RECS_USER,
)

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
        raise RuntimeError(
            f"Missing required GitHub Secret: {name}"
        )
    return value


def generate_content(client, system_prompt, user_prompt):
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": (
                            user_prompt
                            + "\n\nأخرج المنشور النهائي كنص عادي "
                            "جاهز للنشر، ولا ترجع رداً فارغاً."
                        ),
                    },
                ],
                temperature=0.7,
                max_tokens=1000,
            )

            if not response.choices:
                logging.warning(
                    "Attempt %s: AI returned no choices.",
                    attempt,
                )
            else:
                choice = response.choices[0]
                content = choice.message.content
                finish_reason = choice.finish_reason

                if isinstance(content, str) and content.strip():
                    return content.strip()

                logging.warning(
                    "Attempt %s: empty content; finish_reason=%s",
                    attempt,
                    finish_reason,
                )

                if getattr(choice.message, "refusal", None):
                    logging.warning(
                        "AI refusal: %s",
                        choice.message.refusal,
                    )

        except Exception as exc:
            logging.warning(
                "AI attempt %s failed: %s",
                attempt,
                str(exc)[:500],
            )

        if attempt < 3:
            time.sleep(attempt * 2)

    raise RuntimeError(
        "AI returned no usable text after 3 attempts. "
        "Check the logs above for finish_reason or API errors."
    )


def send_telegram_message(bot_token, chat_id, message):
    url = (
        f"https://api.telegram.org/"
        f"bot{bot_token}/sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, 4):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=30,
            )

            try:
                data = response.json()
            except ValueError:
                data = {}

            if response.ok and data.get("ok"):
                message_id = data.get(
                    "result", {}
                ).get("message_id")

                logging.info(
                    "Telegram post sent; message_id=%s",
                    message_id,
                )
                return

            logging.error(
                "Telegram HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )

        except requests.RequestException as exc:
            logging.warning(
                "Telegram attempt %s failed: %s",
                attempt,
                exc,
            )

        if attempt < 3:
            time.sleep(attempt * 2)

    raise RuntimeError(
        "Failed to send the post to Telegram after 3 attempts."
    )


def main():
    api_key = required_env("OPENROUTER_API_KEY")
    bot_token = required_env("TELEGRAM_BOT_TOKEN")
    chat_id = required_env("TELEGRAM_CHAT_ID")

    client = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": (
                "https://github.com/mad477382-prog/tele"
            ),
            "X-Title": "FilmFilesX Auto Publisher",
        },
    )

    selected_wing = os.getenv("WING")

    if selected_wing:
        wings_to_run = [
            wing for wing in WINGS
            if wing[0] == selected_wing
        ]

        if not wings_to_run:
            raise RuntimeError(
                f"Unknown WING value: {selected_wing}"
            )
    else:
        wings_to_run = [random.choice(WINGS)]

    for wing_name, system_prompt, user_prompt in wings_to_run:
        logging.info(
            "Generating content using wing: %s",
            wing_name,
        )

        content = generate_content(
            client,
            system_prompt,
            user_prompt,
        )

        logging.info(
            "Generated content successfully (%s characters).",
            len(content),
        )

        send_telegram_message(
            bot_token,
            chat_id,
            content,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("FilmFilesX run failed")
        sys.exit(1)
