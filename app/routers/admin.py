import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.config import get_settings
from app.dependencies import get_db
from app.models import Event, NotificationLog, Subscriber, SubscriberStatus

router = APIRouter(prefix="/admin")
security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates/admin")


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
