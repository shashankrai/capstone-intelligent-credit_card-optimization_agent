"""SQLAlchemy models + CRUD for the non-vector tables (user memory + feedback).

pgvector operations stay in raw psycopg (database/db.py); SQLAlchemy is used here for the
user_profiles and feedback tables — clean ORM access for personalization and Stage-3 feedback.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from sqlalchemy import String, Text, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

import config


def _sqlalchemy_url() -> str:
    auth = config.PGUSER
    if config.PGPASSWORD:
        auth = f"{config.PGUSER}:{quote_plus(config.PGPASSWORD)}"
    return f"postgresql+psycopg://{auth}@{config.PGHOST}:{config.PGPORT}/{config.PGDATABASE}"


@lru_cache(maxsize=1)
def engine():
    return create_engine(_sqlalchemy_url(), future=True)


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    cards_owned: Mapped[list] = mapped_column(JSONB, default=list)
    preferred_reward_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    point_valuation: Mapped[Optional[float]] = mapped_column(nullable=True)
    monthly_spend_pattern: Mapped[dict] = mapped_column(JSONB, default=dict)
    preferred_partners: Mapped[list] = mapped_column(JSONB, default=list)
    conversation_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "cards_owned": self.cards_owned or [],
            "preferred_reward_type": self.preferred_reward_type,
            "point_valuation": float(self.point_valuation) if self.point_valuation is not None else None,
            "monthly_spend_pattern": self.monthly_spend_pattern or {},
            "preferred_partners": self.preferred_partners or [],
            "conversation_summary": self.conversation_summary,
        }


class Feedback(Base):
    __tablename__ = "feedback"

    feedback_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def get_profile(user_id: str) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    with Session(engine()) as s:
        row = s.get(UserProfile, user_id)
        return row.as_dict() if row else None


def upsert_profile(user_id: str, **fields) -> Dict[str, Any]:
    """Create or update a profile. Only provided, non-None fields are written."""
    with Session(engine()) as s:
        row = s.get(UserProfile, user_id)
        if row is None:
            row = UserProfile(user_id=user_id, cards_owned=[], monthly_spend_pattern={},
                              preferred_partners=[])
            s.add(row)
        for key, value in fields.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        s.commit()
        return row.as_dict()


def add_feedback(query_id: Optional[int], user_id: Optional[str], rating: str,
                 note: Optional[str] = None) -> int:
    with Session(engine()) as s:
        fb = Feedback(query_id=query_id, user_id=user_id, rating=rating, note=note)
        s.add(fb)
        s.commit()
        return fb.feedback_id


def feedback_summary() -> Dict[str, int]:
    with Session(engine()) as s:
        ups = len(s.execute(select(Feedback).where(Feedback.rating == "up")).all())
        downs = len(s.execute(select(Feedback).where(Feedback.rating == "down")).all())
    return {"up": ups, "down": downs}
