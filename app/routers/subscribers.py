import logging
import secrets
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.dependencies import get_db
from app.google_calendar import get_calendar_share_link
from app.models import Subscriber, SubscriberStatus
from app.notifications.email import format_welcome_email, get_email_sender
from app.notifications.telegram import TelegramNotifier, format_welcome_message

log = logging.getLogger(__name__)

router = APIRouter()


class SubscribeRequest(BaseModel):
    email: EmailStr
    telegram_chat_id: str | None = None


class SubscribeResponse(BaseModel):
    success: bool
    message: str


async def _send_welcome(email: str, telegram_chat_id: str | None) -> None:
    calendar_link = get_calendar_share_link()

    # Welcome email
    sender = get_email_sender()
    html = format_welcome_email(calendar_link)
    await sender.send(email, "Vitej v DataTalk Events!", html)

    # Welcome Telegram
    if telegram_chat_id:
        telegram = TelegramNotifier()
        text = format_welcome_message(calendar_link)
        await telegram.send_message(telegram_chat_id, text)


@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(
    req: SubscribeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing = db.exec(select(Subscriber).where(Subscriber.email == req.email)).first()
    if existing and existing.status == SubscriberStatus.VERIFIED:
        raise HTTPException(409, "Already subscribed")
    if existing:
        return SubscribeResponse(success=True, message="Verification email sent")

    token = secrets.token_urlsafe(32)
    subscriber = Subscriber(
        email=req.email,
        telegram_chat_id=req.telegram_chat_id,
        verification_token=token,
    )
    db.add(subscriber)
    db.commit()
    return SubscribeResponse(success=True, message="Verification email sent")


@router.get("/verify")
def verify_email(
    token: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    subscriber = db.exec(
        select(Subscriber).where(Subscriber.verification_token == token)
    ).first()
    if not subscriber:
        raise HTTPException(400, "Invalid or expired token")
    subscriber.status = SubscriberStatus.VERIFIED
    subscriber.verified_at = datetime.utcnow()
    subscriber.verification_token = None
    db.commit()

    # Send welcome after verification
    background_tasks.add_task(
        _send_welcome, subscriber.email, subscriber.telegram_chat_id
    )

    return {"success": True, "message": "Email verified! Check your inbox for the calendar link."}


@router.post("/unsubscribe")
def unsubscribe(req: SubscribeRequest, db: Session = Depends(get_db)):
    subscriber = db.exec(select(Subscriber).where(Subscriber.email == req.email)).first()
    if subscriber:
        subscriber.status = SubscriberStatus.UNSUBSCRIBED
        db.commit()
    return {"success": True}
