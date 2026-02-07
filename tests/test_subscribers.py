from datetime import datetime

from sqlmodel import select

from app.models import Subscriber, SubscriberStatus


class TestSubscribe:
    def test_subscribe_creates_pending_subscriber(self, client, session) -> None:
        response = client.post("/subscribe", json={"email": "new@example.com"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Verification email sent"

        subscriber = session.exec(
            select(Subscriber).where(Subscriber.email == "new@example.com")
        ).first()
        assert subscriber is not None
        assert subscriber.status == SubscriberStatus.PENDING
        assert subscriber.verification_token is not None

    def test_subscribe_duplicate_verified_returns_409(self, client, session) -> None:
        subscriber = Subscriber(
            email="verified@example.com",
            status=SubscriberStatus.VERIFIED,
            verified_at=datetime.utcnow(),
        )
        session.add(subscriber)
        session.commit()

        response = client.post("/subscribe", json={"email": "verified@example.com"})
        assert response.status_code == 409


class TestVerify:
    def test_verify_valid_token(self, client, session) -> None:
        subscriber = Subscriber(
            email="pending@example.com",
            verification_token="test-token-123",
        )
        session.add(subscriber)
        session.commit()

        response = client.get("/verify", params={"token": "test-token-123"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        session.refresh(subscriber)
        assert subscriber.status == SubscriberStatus.VERIFIED
        assert subscriber.verified_at is not None
        assert subscriber.verification_token is None

    def test_verify_invalid_token(self, client) -> None:
        response = client.get("/verify", params={"token": "bad-token"})
        assert response.status_code == 400


class TestUnsubscribe:
    def test_unsubscribe(self, client, session) -> None:
        subscriber = Subscriber(
            email="unsub@example.com",
            status=SubscriberStatus.VERIFIED,
            verified_at=datetime.utcnow(),
        )
        session.add(subscriber)
        session.commit()

        response = client.post("/unsubscribe", json={"email": "unsub@example.com"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        session.refresh(subscriber)
        assert subscriber.status == SubscriberStatus.UNSUBSCRIBED
