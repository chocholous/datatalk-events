import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.dependencies import get_db
from app.models import Subscriber, SubscriberStatus

router = APIRouter()


class SubscribeRequest(BaseModel):
    email: EmailStr
    telegram: str | None = None


class SubscribeResponse(BaseModel):
    success: bool
    message: str


@router.post("/subscribe", response_model=SubscribeResponse)
def subscribe(req: SubscribeRequest, db: Session = Depends(get_db)):
    existing = db.exec(select(Subscriber).where(Subscriber.email == req.email)).first()
    if existing and existing.status == SubscriberStatus.VERIFIED:
        raise HTTPException(409, "Already subscribed")
    if existing:
        # Resend verification for pending subscriber
        return SubscribeResponse(success=True, message="Verification email sent")

    token = secrets.token_urlsafe(32)
    subscriber = Subscriber(
        email=req.email,
        telegram_chat_id=req.telegram,
        verification_token=token,
    )
    db.add(subscriber)
    db.commit()
    return SubscribeResponse(success=True, message="Verification email sent")


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    subscriber = db.exec(
        select(Subscriber).where(Subscriber.verification_token == token)
    ).first()
    if not subscriber:
        raise HTTPException(400, "Invalid or expired token")
    subscriber.status = SubscriberStatus.VERIFIED
    subscriber.verified_at = datetime.utcnow()
    subscriber.verification_token = None
    db.commit()
    return {"success": True, "message": "Email verified!"}


@router.post("/unsubscribe")
def unsubscribe(req: SubscribeRequest, db: Session = Depends(get_db)):
    subscriber = db.exec(select(Subscriber).where(Subscriber.email == req.email)).first()
    if subscriber:
        subscriber.status = SubscriberStatus.UNSUBSCRIBED
        db.commit()
    return {"success": True}
