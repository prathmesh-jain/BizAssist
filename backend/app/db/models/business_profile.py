import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BusinessProfile(Base, TimestampMixin):
    """The organization's business profile: onboarding answers plus the user-confirmed result.

    Only a profile with status "confirmed" is used as context by the assistant. Research
    proposals live in BusinessResearchRun until a user reviews and confirms them.
    """
    __tablename__ = "business_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")  # draft, confirmed

    # Identity and classification
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    subdomain: Mapped[str | None] = mapped_column(String, nullable=True)
    business_model: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    scale: Mapped[str | None] = mapped_column(String, nullable=True)
    geography: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lists the user curates
    products_services: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    customer_segments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    goals: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    challenges: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    existing_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    monitoring_preferences: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    competitors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    opportunities: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Industry-specific answers from conditional onboarding questions, keyed by question id.
    answers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Where each confirmed field came from: {"field": {"basis": ..., "sources": [...]}}.
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by_user_id: Mapped[str | None] = mapped_column(String, ForeignKey("users.id"), nullable=True)
    onboarding_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BusinessResearchRun(Base, TimestampMixin):
    """One execution of the business research workflow and its reviewable proposal."""
    __tablename__ = "business_research_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        String, ForeignKey("organizations.id"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued, running, completed, failed
    # Snapshot of the onboarding input the research started from.
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Human-readable progress steps, appended as the workflow advances.
    progress: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Proposal: profile fields with provenance, competitors, opportunities, sources, warnings.
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_business_research_runs_org_created", "organization_id", "created_at"),
        # At most one active run per organization.
        Index(
            "uq_business_research_runs_active",
            "organization_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )
