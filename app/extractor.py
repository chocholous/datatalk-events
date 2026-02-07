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

IMPORTANT: Always include the TIME (not just the date). Look for start/end times
in JSON-LD (startDate/endDate), in the markdown content, or in the title/description.
Use full ISO 8601 datetime format like "2026-03-15T18:00:00". If only a date is known
without a specific time, use T09:00:00 as default start time.

Return a JSON array with objects containing:
- title: string
- date: ISO 8601 datetime string with time (e.g. "2026-03-15T18:00:00") or null
- end_date: ISO 8601 datetime string with time or null
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
            log.warning("OpenAI API key not set, using fallback extraction from structured data")
            return [self._extract_from_structured_data(e) for e in events]

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

    def _extract_from_structured_data(self, event: dict) -> dict:
        """Fallback: extract fields from JSON-LD and OpenGraph when no LLM is available."""
        json_ld = event.get("json_ld") or {}
        og = event.get("og_meta") or {}

        # Location from JSON-LD
        location = None
        ld_location = json_ld.get("location")
        if isinstance(ld_location, dict):
            location = ld_location.get("name") or ld_location.get("address")
            if isinstance(location, dict):
                location = location.get("addressLocality")
        elif isinstance(ld_location, str):
            location = ld_location

        # Organizer from JSON-LD
        organizer = None
        ld_organizer = json_ld.get("organizer")
        if isinstance(ld_organizer, dict):
            organizer = ld_organizer.get("name")
        elif isinstance(ld_organizer, str):
            organizer = ld_organizer

        # Speakers/performers from JSON-LD
        speakers = []
        for key in ("performer", "performers"):
            performers = json_ld.get(key)
            if performers:
                if isinstance(performers, list):
                    for p in performers:
                        if isinstance(p, dict):
                            name = p.get("name")
                            if name:
                                speakers.append(name)
                        elif isinstance(p, str):
                            speakers.append(p)
                elif isinstance(performers, dict):
                    name = performers.get("name")
                    if name:
                        speakers.append(name)

        # Image from OG meta or JSON-LD
        image_url = og.get("og:image")
        if not image_url:
            ld_image = json_ld.get("image")
            if isinstance(ld_image, str):
                image_url = ld_image
            elif isinstance(ld_image, dict):
                image_url = ld_image.get("url")
            elif isinstance(ld_image, list) and ld_image:
                first = ld_image[0]
                image_url = first if isinstance(first, str) else first.get("url") if isinstance(first, dict) else None

        # Description from OG meta or JSON-LD
        description = (
            og.get("og:description")
            or json_ld.get("description")
            or event.get("description")
        )

        return {
            "title": json_ld.get("name") or og.get("og:title") or event.get("title", ""),
            "url": event.get("url", ""),
            "date": json_ld.get("startDate"),
            "end_date": json_ld.get("endDate"),
            "location": location,
            "topics": [],
            "type": None,
            "level": None,
            "language": None,
            "description": description,
            "speakers": speakers,
            "organizer": organizer,
            "image_url": image_url,
        }
