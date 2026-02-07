from datetime import datetime

from app.models import Event


class TestListEvents:
    def test_list_events(self, client, session) -> None:
        event1 = Event(
            external_id="list-evt-1",
            title="Event One",
            url="https://example.com/1",
        )
        event2 = Event(
            external_id="list-evt-2",
            title="Event Two",
            url="https://example.com/2",
        )
        session.add(event1)
        session.add(event2)
        session.commit()

        response = client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestGetEventIcal:
    def test_get_event_ical(self, client, session) -> None:
        event = Event(
            external_id="ical-evt-1",
            title="iCal Test Event",
            url="https://example.com/ical",
            date=datetime(2025, 6, 15, 14, 0, 0),
            location="Prague",
            description="A test event for iCal export",
        )
        session.add(event)
        session.commit()
        session.refresh(event)

        response = client.get(f"/events/{event.id}/ical")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/calendar; charset=utf-8"
        content = response.content
        assert b"BEGIN:VCALENDAR" in content
        assert b"iCal Test Event" in content
        assert b"Prague" in content

    def test_get_event_ical_not_found(self, client) -> None:
        response = client.get("/events/999/ical")
        assert response.status_code == 404


class TestTriggerScrape:
    def test_trigger_scrape(self, client) -> None:
        response = client.post("/scrape")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
