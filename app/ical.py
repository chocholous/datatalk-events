from datetime import timedelta

from icalendar import Calendar, Event as ICalEvent

from app.models import Event


def event_to_ical(event: Event) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//DataTalk Events//datatalk.cz//")
    cal.add("version", "2.0")

    ical_event = ICalEvent()
    ical_event.add("summary", event.title)
    if event.date:
        ical_event.add("dtstart", event.date)
        if event.end_date:
            ical_event.add("dtend", event.end_date)
        else:
            ical_event.add("dtend", event.date + timedelta(hours=2))
    if event.location:
        ical_event.add("location", event.location)
    if event.description:
        ical_event.add("description", event.description)
    ical_event.add("url", event.url)

    cal.add_component(ical_event)
    return cal.to_ical()
