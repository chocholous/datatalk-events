import asyncio
import json
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, func, select

from app.config import get_settings
from app.dependencies import get_db
from app.models import Event, ScrapeRun
from app.notifications.pipeline import run_scrape_and_sync

router = APIRouter(prefix="/admin")
security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates/admin")


def _parse_json_list(value: str) -> list[str]:
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
    total_events = db.exec(select(func.count(Event.id))).one()
    last_event = db.exec(
        select(Event).order_by(Event.scraped_at.desc()).limit(1)
    ).first()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "total_events": total_events,
            "last_scrape": last_event.scraped_at if last_event else None,
        },
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
    asyncio.run(run_scrape_and_sync(db))


@router.post("/scrape")
def trigger_scrape(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    admin: str = Depends(verify_admin),
):
    background.add_task(_run_pipeline, db)
    return RedirectResponse("/admin/?message=scrape_started", status_code=303)


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
