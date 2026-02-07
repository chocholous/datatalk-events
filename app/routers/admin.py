import asyncio
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.config import get_settings
from app.dependencies import get_db
from app.models import Event, NotificationLog, ScrapeRun, Subscriber, SubscriberStatus
from app.notifications.pipeline import run_scrape_and_notify

router = APIRouter(prefix="/admin")
security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates/admin")


def _parse_json_list(value: str) -> list[str]:
    """Parse a JSON array string, returning empty list on failure."""
    if not value or value == "[]":
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


templates.env.filters["parse_json_list"] = _parse_json_list


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    settings = get_settings()
    username_ok = secrets.compare_digest(
        credentials.username.encode(), settings.admin_username.encode()
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(), settings.admin_password.encode()
    )
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    total_subscribers = db.exec(select(func.count(Subscriber.id))).one()
    verified = db.exec(
        select(func.count(Subscriber.id)).where(
            Subscriber.status == SubscriberStatus.VERIFIED
        )
    ).one()
    pending = db.exec(
        select(func.count(Subscriber.id)).where(
            Subscriber.status == SubscriberStatus.PENDING
        )
    ).one()
    total_events = db.exec(select(func.count(Event.id))).one()
    last_event = db.exec(
        select(Event).order_by(Event.scraped_at.desc()).limit(1)
    ).first()
    last_notification = db.exec(
        select(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(1)
    ).first()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_subscribers": total_subscribers,
            "verified": verified,
            "pending": pending,
            "total_events": total_events,
            "last_scrape": last_event.scraped_at if last_event else None,
            "last_notification": last_notification.sent_at
            if last_notification
            else None,
        },
    )


@router.get("/subscribers", response_class=HTMLResponse)
def subscribers_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    subscribers = db.exec(
        select(Subscriber).order_by(Subscriber.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        "subscribers.html", {"request": request, "subscribers": subscribers}
    )


@router.get("/events", response_class=HTMLResponse)
def events_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    events = db.exec(select(Event).order_by(Event.scraped_at.desc())).all()
    return templates.TemplateResponse(
        "events.html", {"request": request, "events": events}
    )


def _run_pipeline(db: Session) -> None:
    """Run the async pipeline in a new event loop for background tasks."""
    asyncio.run(run_scrape_and_notify(db))


@router.post("/scrape")
def trigger_scrape(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    background.add_task(_run_pipeline, db)
    return RedirectResponse("/admin/?message=scrape_started", status_code=303)


@router.post("/subscribers")
async def add_subscriber(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    form = await request.form()
    email = form.get("email", "").strip()
    if not email:
        return RedirectResponse("/admin/subscribers?error=email_required", status_code=303)

    telegram_chat_id = form.get("telegram_chat_id", "").strip() or None
    status_val = form.get("status", "pending")

    existing = db.exec(select(Subscriber).where(Subscriber.email == email)).first()
    if existing:
        existing.status = SubscriberStatus(status_val)
        existing.telegram_chat_id = telegram_chat_id
        if status_val == "verified" and existing.verified_at is None:
            existing.verified_at = datetime.utcnow()
        db.commit()
        return RedirectResponse("/admin/subscribers?message=subscriber_updated", status_code=303)

    subscriber = Subscriber(
        email=email,
        telegram_chat_id=telegram_chat_id,
        status=SubscriberStatus(status_val),
    )
    if status_val == "verified":
        subscriber.verified_at = datetime.utcnow()

    db.add(subscriber)
    db.commit()
    return RedirectResponse("/admin/subscribers?message=subscriber_added", status_code=303)


@router.get("/runs", response_class=HTMLResponse)
def runs_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    runs = db.exec(select(ScrapeRun).order_by(ScrapeRun.started_at.desc())).all()
    return templates.TemplateResponse(
        "runs.html", {"request": request, "runs": runs}
    )


@router.get("/notifications", response_class=HTMLResponse)
def notifications_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    results = db.exec(
        select(NotificationLog, Subscriber, Event)
        .join(Subscriber, NotificationLog.subscriber_id == Subscriber.id)
        .join(Event, NotificationLog.event_id == Event.id)
        .order_by(NotificationLog.sent_at.desc())
    ).all()
    logs = [
        {"notification": row[0], "subscriber": row[1], "event": row[2]}
        for row in results
    ]
    return templates.TemplateResponse(
        "notifications.html", {"request": request, "logs": logs}
    )
