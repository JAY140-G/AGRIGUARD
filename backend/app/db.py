from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Float, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

class Base(DeclarativeBase): pass

def now(): return datetime.now(timezone.utc)

engine = create_engine(settings.database_url, connect_args={'check_same_thread': False} if settings.database_url.startswith('sqlite') else {}, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password: Mapped[str] = mapped_column(String)

class Login(Base):
    __tablename__ = 'logins'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Farm(Base):
    __tablename__ = 'farms'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String)
    crop: Mapped[str] = mapped_column(String)
    planting_date: Mapped[str | None] = mapped_column(String, nullable=True)
    boundary: Mapped[str] = mapped_column(Text)
    area_ha: Mapped[float] = mapped_column(Float)

class Mission(Base):
    __tablename__ = 'missions'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey('farms.id'), index=True)
    state: Mapped[str] = mapped_column(String, default='planned')
    plan: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    progress: Mapped[float] = mapped_column(Float, default=0)
    telemetry: Mapped[str] = mapped_column(Text, default='{}')
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

class Photo(Base):
    __tablename__ = 'photos'
    __table_args__ = (UniqueConstraint('farm_id','digest'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    farm_id: Mapped[str] = mapped_column(ForeignKey('farms.id'), index=True)
    mission_id: Mapped[str | None] = mapped_column(ForeignKey('missions.id'), nullable=True)
    digest: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    captured: Mapped[str] = mapped_column(String)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')
    domain: Mapped[str] = mapped_column(String)
    simulated: Mapped[bool]
    status: Mapped[str] = mapped_column(String, default='queued')
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String, nullable=True)

class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey('photos.id'), unique=True)
    status: Mapped[str] = mapped_column(String, default='queued')
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
