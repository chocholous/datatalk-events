import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class EventExtractor:
    """Extract structured data using OpenAI LLM."""

    PROMPT = """Analyze these events and extract structured data.
Return a JSON array with objects containing:
- title: string
- date: ISO date string or null
- location: "online" or city name or null
- topics: array of tags like ["AI", "Data", "Python"]
- type: "workshop" | "meetup" | "conference" | "webinar"
- level: "beginner" | "intermediate" | "advanced" | null
- language: "cs" | "en" | null
- url: string (preserve from input)
- description: short summary string

Events to analyze:
{events}

Return ONLY valid JSON array, no markdown."""

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def extract(self, events: list[dict]) -> list[dict]:
        settings = get_settings()
        if not settings.openai_api_key:
            log.warning("OpenAI API key not set, returning raw events")
            return events

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                OPENAI_API_URL,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": self.PROMPT.format(
                                events=json.dumps(events, ensure_ascii=False)
                            ),
                        }
                    ],
                    "temperature": 0.1,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            # Clean markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]

            return json.loads(content)
