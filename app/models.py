from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Double, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    clerk_id:   Mapped[str]            = mapped_column(String, primary_key=True)
    email:      Mapped[str | None]     = mapped_column(String, nullable=True)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents:     Mapped[list[Document]]    = relationship(back_populates="user", cascade="all, delete-orphan")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id:           Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:      Mapped[str]          = mapped_column(String, ForeignKey("users.clerk_id"), nullable=False)
    filename:     Mapped[str]          = mapped_column(String, nullable=False)
    status:        Mapped[str]          = mapped_column(String, default="uploaded")
    source_type:   Mapped[str]          = mapped_column(String, default="pdf", server_default="pdf")
    page_count:    Mapped[int | None]   = mapped_column(Integer, nullable=True)
    index_time_s:  Mapped[float | None] = mapped_column(Double, nullable=True)
    error_message:        Mapped[str | None]   = mapped_column(Text, nullable=True)
    celery_task_id:       Mapped[str | None]   = mapped_column(String, nullable=True)
    stopped_at_progress:  Mapped[int | None]   = mapped_column(Integer, nullable=True)
    stopped_at_step:      Mapped[str | None]   = mapped_column(String, nullable=True)
    created_at:           Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    user:          Mapped[User]           = relationship(back_populates="documents")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="document")


class Conversation(Base):
    __tablename__ = "conversations"

    id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:    Mapped[str]            = mapped_column(String, ForeignKey("users.clerk_id"), nullable=False)
    doc_id:     Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    title:      Mapped[str | None]     = mapped_column(String, nullable=True)
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

    user:     Mapped[User]         = relationship(back_populates="conversations")
    document: Mapped[Document | None] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]]   = relationship(back_populates="conversation", cascade="all, delete-orphan")


class IngestionEvent(Base):
    __tablename__ = "ingestion_events"

    id:         Mapped[uuid.UUID]      = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:    Mapped[str]            = mapped_column(String, ForeignKey("users.clerk_id"), nullable=False)
    doc_id:     Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    tokens_in:  Mapped[int]            = mapped_column(Integer, default=0, server_default="0")
    tokens_out: Mapped[int]            = mapped_column(Integer, default=0, server_default="0")
    cost_usd:   Mapped[float]          = mapped_column(Double, default=0.0, server_default="0.0")
    created_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id:              Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID]    = mapped_column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    role:            Mapped[str]          = mapped_column(String, nullable=False)
    content:         Mapped[str]          = mapped_column(Text, nullable=False)
    citations:       Mapped[dict | None]  = mapped_column(JSONB, nullable=True)
    tokens_in:       Mapped[int | None]   = mapped_column(Integer, nullable=True)
    tokens_out:      Mapped[int | None]   = mapped_column(Integer, nullable=True)
    cost_usd:        Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at:      Mapped[datetime]     = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id:           Mapped[uuid.UUID]        = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id:      Mapped[str]              = mapped_column(String, ForeignKey("users.clerk_id", ondelete="CASCADE"), nullable=False)
    key_hash:     Mapped[str]              = mapped_column(String, nullable=False, unique=True)
    name:         Mapped[str]              = mapped_column(String, nullable=False, default="Default")
    created_at:   Mapped[datetime]         = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None]  = mapped_column(DateTime(timezone=True), nullable=True)
