"""Database models for Comidas Campo (SQLAlchemy + SQLite)."""

from datetime import datetime, timedelta

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Family(db.Model):
    """A family that may attend events. The list is fairly stable."""

    __tablename__ = "families"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Event(db.Model):
    """A stay at the country house (a weekend, a holiday, a whole summer)."""

    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default="open", nullable=False)  # open | closed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    participations = db.relationship(
        "Participation", backref="event", cascade="all, delete-orphan"
    )
    attendances = db.relationship(
        "Attendance", backref="event", cascade="all, delete-orphan"
    )
    expenses = db.relationship(
        "Expense", backref="event", cascade="all, delete-orphan"
    )

    def days(self):
        """Inclusive list of date objects from start_date to end_date."""
        out = []
        d = self.start_date
        while d <= self.end_date:
            out.append(d)
            d += timedelta(days=1)
        return out

    @property
    def is_open(self):
        return self.status == "open"

    @property
    def num_days(self):
        return (self.end_date - self.start_date).days + 1


class Participation(db.Model):
    """Links a family to an event and tracks whether it finished entering data."""

    __tablename__ = "participations"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    family_id = db.Column(db.Integer, db.ForeignKey("families.id"), nullable=False)
    submitted = db.Column(db.Boolean, default=False, nullable=False)

    family = db.relationship("Family")

    __table_args__ = (db.UniqueConstraint("event_id", "family_id"),)


class Attendance(db.Model):
    """How many people a family brought on a given day. Missing row = 0 people."""

    __tablename__ = "attendances"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    family_id = db.Column(db.Integer, db.ForeignKey("families.id"), nullable=False)
    day = db.Column(db.Date, nullable=False)
    num_people = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (db.UniqueConstraint("event_id", "family_id", "day"),)


class Expense(db.Model):
    """A single food expense paid by a family during an event (pesos, integer)."""

    __tablename__ = "expenses"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    family_id = db.Column(db.Integer, db.ForeignKey("families.id"), nullable=False)
    amount = db.Column(db.Integer, default=0, nullable=False)
    description = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    family = db.relationship("Family")
