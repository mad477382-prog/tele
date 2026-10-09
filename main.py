
import logging
import os
import random
import sys
import time

import requests
from openai import OpenAI

from wings import movie_facts, cinema_quiz, movie_recommendations


# ---------- Settings ----------

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "meta-llama/llama-3-8b-instruct:free",
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

WINGS = [
    ("movie_facts", movie_facts),
    ("cinema_quiz", cinema_quiz),
    ("movie_recommendations", movie_recommendations),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("FilmFilesX")


def required_env(name):
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value.strip()


def create_client():
    return OpenAI(
        api_key=required_env("OPENROUTER_API_KEY"),
        base_url=OPENROUTER_BASE_URL,
        timeout=45.0,
        max_retries=2,
    )


def choose_wing():
    """Choose one content wing randomly."""
    return random.choice(WINGS)


def generate_content(client, wing_name, wing):
    logger.info("Generating content using wing: %s", wing_name)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": wing.SYSTEM_PROMPT},
            {"role": "user", "content": wing.USER_PROMPT},
        ],
        temperature=0.7,
        max_tokens=450,
    )

    content = response.choices[0].message.content

    if not content or not content.strip():
        raise RuntimeError("OpenRouter returned empty content")

    content = content.strip()

    # Telegram's sendMessage text limit is 4096 characters.
    if len(content) > 3800:
        content = content[:3790].rsplit(" ", 1)[0].rstrip() + "…"

    return content


def validate_content(content):
    """Basic quality checks, not factual verification."""
    if not content or len(content.strip()) < 40:
        raise ValueError("Generated content is too short")

    if len(content) > 4096:
        raise ValueError("Generated content exceeds Telegram limit")

    blocked_phrases = [
        "as an ai language model",
        "بصفتي نموذج ذكاء اصطناعي",
        "إليك المنشور المطلوب",
    ]

    lowered = content.lower()
    if any(phrase in lowered for phrase in blocked_phrases):
        raise ValueError("Generated content contains unwanted boilerplate")

    return content


def send_to_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    # Retry temporary failures. Do not blindly retry after an
    # ambiguous network timeout because Telegram may have accepted it.
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=20,
            )
        except requests.Timeout as exc:
            raise RuntimeError(
                "Telegram request timed out; delivery status is unknown"
            ) from exc
        except requests.RequestException as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Telegram network error: {exc}") from exc

        if response.ok:
            result = response.json()
            if result.get("ok") is True:
                message_id = result.get("result", {}).get("message_id")
                logger.info("Telegram post sent; message_id=%s", message_id)
                return

        # Rate limits and temporary server errors may be retried.
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < 2:
                try:
                    data = response.json()
                    wait = data.get("parameters", {}).get(
                        "retry_after", 2 ** attempt
                    )
                except ValueError:
                    wait = 2 ** attempt

                time.sleep(min(max(int(wait), 1), 60))
                continue

        raise RuntimeError(
            f"Telegram API error {response.status_code}: "
            f"{response.text[:500]}"
        )

    raise RuntimeError("Telegram delivery failed after retries")


def main():
    # Validate secrets before making external requests.
    telegram_token = required_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = required_env("TELEGRAM_CHAT_ID")
    client = create_client()

    wing_name, wing = choose_wing()
    content = generate_content(client, wing_name, wing)
    content = validate_content(content)

    send_to_telegram(
        telegram_token,
        telegram_chat_id,
        content,
    )

    logger.info("Run completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("FilmFilesX run failed")
        sys.exit(1)
