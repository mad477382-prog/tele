import os
import sys
import time
import random
import logging
import re
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
BASE_URL = "https://openrouter.ai/api/v1"

WINGS = [
    ("movie_facts", FACTS_SYSTEM, FACTS_USER),
    ("cinema_quiz", QUIZ_SYSTEM, QUIZ_USER),
    ("movie_recommendations", RECS_SYSTEM, RECS_USER),
]


def required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing GitHub Secret: {name}")
    return value


def generate_content(client, system_prompt, user_prompt):
    prompt = user_prompt + """

تعليمات مهمة:
- اكتب المنشور بعربية سليمة وطبيعية.
- لا تخلط كلمات إنكليزية داخل الجمل العربية.
- استخدم عنواناً جذاباً وفقرات قصيرة ورموزاً تعبيرية باعتدال.
- رتّب المنشور حتى يكون مناسباً لقناة تلغرام سينمائية.
- لا تخترع معلومات أو تقييمات أو جوائز.
- لا تستخدم تنسيق Markdown المعقد.
- أخرج المنشور النهائي فقط.
"""

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=1000,
            )

            if response.choices:
                content = response.choices[0].message.content
                if isinstance(content, str) and content.strip():
                    return content.strip()

            logging.warning("Empty AI response, attempt %s", attempt)

        except Exception as exc:
            logging.warning("AI attempt %s failed: %s", attempt, exc)

        if attempt < 3:
            time.sleep(attempt * 2)

    raise RuntimeError("AI failed to generate a usable post.")


def find_movie_image(message):
    # حاول استخراج اسم الفيلم من سطر العنوان
    patterns = [
        r"(?:العمل|الفيلم|المسلسل)\s*[:：-]\s*([^\n(]+?)(?:\s*\((\d{4})\))?\s*(?:\n|$)",
        r"\*\*([^*\n]+?)\s*\((\d{4})\)\*\*",
    ]

    title = None
    year = None

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            title = match.group(1).strip(" *:-")
            if match.lastindex and match.lastindex >= 2:
                year = match.group(2)
            break

    if not title:
        logging.info("No movie title found for image search.")
        return None

    query = f"{title} film {year or ''}".strip()

    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": query,
                "gsrnamespace": 0,
                "gsrlimit": 5,
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": 900,
                "format": "json",
            },
            headers={"User-Agent": "FilmFilesXBot/1.0"},
            timeout=15,
        )
        response.raise_for_status()

        pages = response.json().get("query", {}).get("pages", {})
        candidates = list(pages.values())
        candidates.sort(
            key=lambda page: title.lower() not in page.get("title", "").lower()
        )

        for page in candidates:
            image_url = page.get("thumbnail", {}).get("source")
            if image_url and image_url.startswith("https://"):
                logging.info("Found image: %s", page.get("title"))
                return image_url

    except (requests.RequestException, ValueError) as exc:
        logging.warning("Image search failed: %s", exc)

    logging.info("No image found; will publish text only.")
    return None


def send_telegram(bot_token, chat_id, message, image_url=None):
    if image_url:
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": message[:1024],
        }
    else:
        endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
        }

    for attempt in range(1, 4):
        try:
            response = requests.post(
                endpoint,
                json=payload,
                timeout=45,
            )

            try:
                result = response.json()
            except ValueError:
                result = {}

            if response.ok and result.get("ok"):
                logging.info("Telegram post sent successfully.")
                return

            logging.error(
                "Telegram HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )

            # إذا فشل إرسال الصورة، جرّب نشر النص وحده.
            if image_url and response.status_code == 400:
                logging.warning("Retrying without image.")
                send_telegram(bot_token, chat_id, message)
                return

        except requests.RequestException as exc:
            logging.warning("Telegram attempt %s failed: %s", attempt, exc)

        if attempt < 3:
            time.sleep(attempt * 2)

    raise RuntimeError("Failed to send post to Telegram.")


def main():
    api_key = required_env("OPENROUTER_API_KEY")
    bot_token = required_env("TELEGRAM_BOT_TOKEN")
    chat_id = required_env("TELEGRAM_CHAT_ID")

    client = OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/mad477382-prog/tele",
            "X-Title": "FilmFilesX Auto Publisher",
        },
    )

    selected_wing = os.getenv("WING")

    if selected_wing:
        selected = [wing for wing in WINGS if wing[0] == selected_wing]
        if not selected:
            raise RuntimeError(f"Unknown WING: {selected_wing}")
    else:
        selected = [random.choice(WINGS)]

    for name, system_prompt, user_prompt in selected:
        logging.info("Generating post: %s", name)

        content = generate_content(
            client,
            system_prompt,
            user_prompt,
        )

        image_url = None
        if name == "movie_recommendations":
            image_url = find_movie_image(content)

        send_telegram(
            bot_token,
            chat_id,
            content,
            image_url,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("FilmFilesX failed")
        sys.exit(1)
