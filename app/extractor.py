import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class EventExtractor:
    """Extract structured data using OpenAI LLM."""

    PROMPT = """Analyze these events and extract structured data. For each event you receive:
- Basic info from calendar listing
- JSON-LD structured data from the event detail page (if available)
- OpenGraph meta tags from the detail page
- Markdown content of the detail page

Use ALL available sources. JSON-LD is the most reliable for dates, locations,
and organizers. Use the markdown content to find speakers, detailed descriptions,
and any info not in structured data.

Return a JSON array with objects containing:
- title: string
- date: ISO date string or null
- end_date: ISO date string or null
- location: "online" or city name or null
- topics: array of tags like ["AI", "Data", "Python"]
- type: "workshop" | "meetup" | "conference" | "webinar"
- level: "beginner" | "intermediate" | "advanced" | null
- language: "cs" | "en" | null
- url: string (preserve from input)
- description: 2-3 sentence summary in Czech
- speakers: array of speaker names (strings)
- organizer: string or null
- image_url: string URL or null

Events to analyze:
{events}

Return ONLY valid JSON array, no markdown."""

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def extract(self, events: list[dict]) -> list[dict]:
        settings = get_settings()
        if not settings.openai_api_key:
            log.warning("OpenAI API key not set, returning raw events")
            return events

        # Format enriched payload for LLM
        formatted = []
        for event in events:
            formatted.append(
                {
                    "title": event.get("title"),
                    "url": event.get("url"),
                    "date_text": event.get("date_text"),
                    "json_ld": event.get("json_ld"),
                    "og_meta": event.get("og_meta"),
                    "markdown": (event.get("markdown") or "")[:3000],
                }
            )

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
                                events=json.dumps(formatted, ensure_ascii=False)
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
