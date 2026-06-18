"""Comidas Campo — Flask app to split the food bill at the family country house.

Run locally:   python app.py        (http://localhost:5000)
Run in Docker: gunicorn -w 2 -b 0.0.0.0:8080 app:app
"""

import os
from datetime import date
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from calculations import compute_settlement
from models import Attendance, Expense, Event, Family, Participation, db

# --------------------------------------------------------------------------- #
# App configuration
# --------------------------------------------------------------------------- #
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me-please")
# Valores por defecto SÓLO para desarrollo local. En el NAS se sobreescriben con
# variables de entorno (ver deploy.secrets / deploy.sh). No pongas las contraseñas
# reales aquí: este archivo va a git.
app.config["SHARED_PASSWORD"] = os.environ.get("SHARED_PASSWORD", "campo")
app.config["ADMIN_PASSWORD"] = os.environ.get("ADMIN_PASSWORD", "admin")

db_url = os.environ.get("DATABASE_URL")
if not db_url:
    os.makedirs(app.instance_path, exist_ok=True)
    db_url = "sqlite:///" + os.path.join(app.instance_path, "comidas.db")
if db_url.startswith("sqlite:///"):
    sqlite_path = db_url[len("sqlite:///"):]
    sqlite_dir = os.path.dirname(sqlite_path)
    if sqlite_dir:
        os.makedirs(sqlite_dir, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
with app.app_context():
    # create_all() is racy when several gunicorn workers boot at once against a
    # fresh SQLite file (both try to CREATE the same tables). Tolerate the loser
    # of that race, but re-raise any genuine failure (e.g. can't open the DB).
    from sqlalchemy import inspect as _sa_inspect

    try:
        db.create_all()
    except Exception:
        db.session.rollback()
        if not _sa_inspect(db.engine).has_table("families"):
            raise

# --------------------------------------------------------------------------- #
# Jinja filters (Spanish formatting)
# --------------------------------------------------------------------------- #
WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


@app.template_filter("clp")
def clp(value):
    """Format an integer amount as Chilean pesos: 45000 -> $45.000."""
    try:
        n = int(round(value))
    except (TypeError, ValueError):
        return value
    s = format(abs(n), ",d").replace(",", ".")
    return ("-$" + s) if n < 0 else ("$" + s)


@app.template_filter("fecha")
def fecha(d):
    if not d:
        return ""
    return f"{d.day:02d}/{d.month:02d}/{d.year}"


@app.template_filter("fecha_corta")
def fecha_corta(d):
    if not d:
        return ""
    return f"{WEEKDAYS[d.weekday()]} {d.day:02d}/{d.month:02d}"


@app.context_processor
def inject_globals():
    fam = None
    fid = session.get("family_id")
    if fid:
        fam = db.session.get(Family, fid)
    return {"current_family": fam}


# --------------------------------------------------------------------------- #
# Auth helpers
# --------------------------------------------------------------------------- #
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            flash("Necesitas acceso de administrador.", "error")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #
def person_days_map(eid):
    rows = (
        db.session.query(Attendance.family_id, db.func.sum(Attendance.num_people))
        .filter_by(event_id=eid)
        .group_by(Attendance.family_id)
        .all()
    )
    return {fid: int(total or 0) for fid, total in rows}


def paid_amount_map(eid):
    rows = (
        db.session.query(Expense.family_id, db.func.sum(Expense.amount))
        .filter_by(event_id=eid)
        .group_by(Expense.family_id)
        .all()
    )
    return {fid: int(total or 0) for fid, total in rows}


def open_participation_or_redirect(eid):
    """Return (event, participation) if the current family may edit, else flash
    a message and return (event_or_None, None)."""
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    fid = session.get("family_id")
    if not fid:
        flash("Primero selecciona tu familia.", "error")
        return event, None
    if not event.is_open:
        flash("El evento está cerrado; no se puede editar.", "error")
        return event, None
    part = Participation.query.filter_by(event_id=eid, family_id=fid).first()
    if not part:
        flash("Tu familia no participa en este evento.", "error")
        return event, None
    return event, part


# --------------------------------------------------------------------------- #
# Auth routes
# --------------------------------------------------------------------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authed"):
        return redirect(url_for("index"))
    if request.method == "POST":
        if request.form.get("password", "") == app.config["SHARED_PASSWORD"]:
            session["authed"] = True
            return redirect(url_for("index"))
        flash("Contraseña incorrecta.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/login", methods=["GET", "POST"])
@login_required
def admin_login():
    if request.method == "POST":
        if request.form.get("password", "") == app.config["ADMIN_PASSWORD"]:
            session["is_admin"] = True
            flash("Modo administrador activado.", "ok")
            return redirect(url_for("index"))
        flash("Contraseña de administrador incorrecta.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    session.pop("is_admin", None)
    flash("Saliste del modo administrador.", "ok")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------- #
# Main routes
# --------------------------------------------------------------------------- #
@app.route("/")
@login_required
def index():
    events = Event.query.order_by(Event.start_date.desc()).all()
    families = Family.query.filter_by(active=True).order_by(Family.name).all()
    return render_template("index.html", events=events, families=families)


@app.route("/set-family", methods=["POST"])
@login_required
def set_family():
    fid = request.form.get("family_id")
    session["family_id"] = int(fid) if fid else None
    return redirect(request.form.get("next") or url_for("index"))


@app.route("/event/<int:eid>")
@login_required
def event_detail(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    parts = (
        Participation.query.filter_by(event_id=eid)
        .join(Family)
        .order_by(Family.name)
        .all()
    )
    pd_map = person_days_map(eid)
    paid_map = paid_amount_map(eid)
    current_fid = session.get("family_id")
    current_part = next((p for p in parts if p.family_id == current_fid), None)

    # For the admin participant editor: all active families plus any current
    # participant that has since been deactivated, so none ever disappears.
    participant_ids = {p.family_id for p in parts}
    active = Family.query.filter_by(active=True).all()
    by_id = {f.id: f for f in active}
    for p in parts:
        by_id.setdefault(p.family_id, p.family)
    manage_families = sorted(by_id.values(), key=lambda f: f.name)

    return render_template(
        "event_detail.html",
        event=event,
        parts=parts,
        pd_map=pd_map,
        paid_map=paid_map,
        is_admin=bool(session.get("is_admin")),
        current_fid=current_fid,
        current_part=current_part,
        manage_families=manage_families,
        participant_ids=participant_ids,
    )


@app.route("/event/<int:eid>/detalle")
@login_required
def event_audit(eid):
    """Vista de auditoría: cualquiera ve la asistencia día a día y los gastos
    de TODAS las familias para revisar que los datos sean correctos."""
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    parts = (
        Participation.query.filter_by(event_id=eid)
        .join(Family)
        .order_by(Family.name)
        .all()
    )
    families = [p.family for p in parts]
    days = event.days()

    # Matriz de asistencia: att[family_id][day] = personas
    att = {f.id: {} for f in families}
    for a in Attendance.query.filter_by(event_id=eid).all():
        if a.family_id in att:
            att[a.family_id][a.day] = a.num_people

    pd_per_fam = {f.id: sum(att[f.id].values()) for f in families}
    day_totals = {d: sum(att[f.id].get(d, 0) for f in families) for d in days}
    grand_pd = sum(pd_per_fam.values())

    expenses = Expense.query.filter_by(event_id=eid).all()
    expenses.sort(key=lambda e: (e.family.name, e.id))
    spent_per_fam = {f.id: 0 for f in families}
    for e in expenses:
        spent_per_fam[e.family_id] = spent_per_fam.get(e.family_id, 0) + e.amount
    grand_spent = sum(spent_per_fam.values())

    return render_template(
        "event_audit.html",
        event=event,
        families=families,
        days=days,
        att=att,
        pd_per_fam=pd_per_fam,
        day_totals=day_totals,
        grand_pd=grand_pd,
        expenses=expenses,
        spent_per_fam=spent_per_fam,
        grand_spent=grand_spent,
    )


@app.route("/event/<int:eid>/mi-participacion")
@login_required
def participation(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    fid = session.get("family_id")
    if not fid:
        flash("Primero selecciona tu familia.", "error")
        return redirect(url_for("index"))
    part = Participation.query.filter_by(event_id=eid, family_id=fid).first()
    if not part:
        flash(
            "Tu familia no participa en este evento. "
            "Pídele al administrador que la agregue.",
            "error",
        )
        return redirect(url_for("event_detail", eid=eid))
    att = {
        a.day: a.num_people
        for a in Attendance.query.filter_by(event_id=eid, family_id=fid).all()
    }
    expenses = (
        Expense.query.filter_by(event_id=eid, family_id=fid)
        .order_by(Expense.id)
        .all()
    )
    return render_template(
        "participation.html",
        event=event,
        part=part,
        days=event.days(),
        att=att,
        expenses=expenses,
        total_spent=sum(e.amount for e in expenses),
        total_pd=sum(att.values()),
    )


@app.route("/event/<int:eid>/asistencia/guardar", methods=["POST"])
@login_required
def save_attendance(eid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    existing = {
        a.day: a
        for a in Attendance.query.filter_by(event_id=eid, family_id=part.family_id).all()
    }
    for d in event.days():
        raw = request.form.get("day_" + d.isoformat(), "").strip()
        n = int(raw) if raw.isdigit() else 0
        if d in existing:
            existing[d].num_people = n
        elif n > 0:
            db.session.add(
                Attendance(event_id=eid, family_id=part.family_id, day=d, num_people=n)
            )
    db.session.commit()
    flash("Asistencia guardada.", "ok")
    return redirect(url_for("participation", eid=eid))


@app.route("/event/<int:eid>/asistencia/rango", methods=["POST"])
@login_required
def fill_attendance(eid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    try:
        d1 = date.fromisoformat(request.form["desde"])
        d2 = date.fromisoformat(request.form["hasta"])
        n = int(request.form["personas"])
    except (KeyError, ValueError):
        flash("Datos del rango inválidos.", "error")
        return redirect(url_for("participation", eid=eid))
    if n < 0:
        n = 0
    if d2 < d1:
        d1, d2 = d2, d1
    existing = {
        a.day: a
        for a in Attendance.query.filter_by(event_id=eid, family_id=part.family_id).all()
    }
    for d in event.days():
        if d1 <= d <= d2:
            if d in existing:
                existing[d].num_people = n
            else:
                db.session.add(
                    Attendance(
                        event_id=eid, family_id=part.family_id, day=d, num_people=n
                    )
                )
    db.session.commit()
    flash(f"Se aplicaron {n} personas del {fecha(d1)} al {fecha(d2)}.", "ok")
    return redirect(url_for("participation", eid=eid))


def _parse_amount(raw):
    """Parse a pesos amount, tolerating '.' thousands separators and spaces."""
    cleaned = (raw or "").strip().replace(".", "").replace(" ", "")
    try:
        return int(cleaned)
    except ValueError:
        return None


@app.route("/event/<int:eid>/gasto/agregar", methods=["POST"])
@login_required
def add_expense(eid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    amount = _parse_amount(request.form.get("amount"))
    if not amount or amount <= 0:
        flash("El monto debe ser un número mayor que cero.", "error")
        return redirect(url_for("participation", eid=eid))
    db.session.add(
        Expense(
            event_id=eid,
            family_id=part.family_id,
            amount=amount,
            description=request.form.get("description", "").strip()[:200],
        )
    )
    db.session.commit()
    flash("Gasto agregado.", "ok")
    return redirect(url_for("participation", eid=eid))


@app.route("/event/<int:eid>/gasto/<int:gid>/editar", methods=["POST"])
@login_required
def edit_expense(eid, gid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    exp = db.session.get(Expense, gid)
    if not exp or exp.event_id != eid or exp.family_id != part.family_id:
        flash("Gasto no encontrado.", "error")
        return redirect(url_for("participation", eid=eid))
    amount = _parse_amount(request.form.get("amount"))
    if not amount or amount <= 0:
        flash("El monto debe ser un número mayor que cero.", "error")
        return redirect(url_for("participation", eid=eid))
    exp.amount = amount
    exp.description = request.form.get("description", "").strip()[:200]
    db.session.commit()
    flash("Gasto actualizado.", "ok")
    return redirect(url_for("participation", eid=eid))


@app.route("/event/<int:eid>/gasto/<int:gid>/eliminar", methods=["POST"])
@login_required
def delete_expense(eid, gid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    exp = db.session.get(Expense, gid)
    if exp and exp.event_id == eid and exp.family_id == part.family_id:
        db.session.delete(exp)
        db.session.commit()
        flash("Gasto eliminado.", "ok")
    return redirect(url_for("participation", eid=eid))


@app.route("/event/<int:eid>/completar", methods=["POST"])
@login_required
def toggle_submit(eid):
    event, part = open_participation_or_redirect(eid)
    if not part:
        return redirect(url_for("event_detail", eid=eid))
    part.submitted = not part.submitted
    db.session.commit()
    flash(
        "Marcaste tu participación como completada."
        if part.submitted
        else "Marcaste tu participación como pendiente.",
        "ok",
    )
    return redirect(url_for("participation", eid=eid))


@app.route("/event/<int:eid>/liquidacion")
@login_required
def settlement(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    if event.is_open and not session.get("is_admin"):
        flash(
            "La liquidación estará disponible cuando el administrador "
            "cierre el evento.",
            "error",
        )
        return redirect(url_for("event_detail", eid=eid))
    part_fids = [
        p.family_id for p in Participation.query.filter_by(event_id=eid).all()
    ]
    pd_map = person_days_map(eid)
    paid_map = paid_amount_map(eid)
    person_days = {fid: pd_map.get(fid, 0) for fid in part_fids}
    paid = {fid: paid_map.get(fid, 0) for fid in part_fids}
    result = compute_settlement(person_days, paid)
    names = {f.id: f.name for f in Family.query.all()}
    return render_template(
        "settlement.html",
        event=event,
        result=result,
        names=names,
        preview=event.is_open,  # admin viewing before close
    )


# --------------------------------------------------------------------------- #
# Admin routes
# --------------------------------------------------------------------------- #
@app.route("/admin/familias")
@admin_required
def admin_families():
    families = Family.query.order_by(Family.name).all()
    return render_template("admin_families.html", families=families)


@app.route("/admin/familias/agregar", methods=["POST"])
@admin_required
def add_family():
    name = request.form.get("name", "").strip()[:80]
    if not name:
        flash("Ingresa un nombre.", "error")
    elif Family.query.filter_by(name=name).first():
        flash("Ya existe una familia con ese nombre.", "error")
    else:
        db.session.add(Family(name=name))
        db.session.commit()
        flash("Familia agregada.", "ok")
    return redirect(url_for("admin_families"))


@app.route("/admin/familias/<int:fid>/editar", methods=["POST"])
@admin_required
def edit_family(fid):
    fam = db.session.get(Family, fid)
    if not fam:
        abort(404)
    name = request.form.get("name", "").strip()[:80]
    if name:
        fam.name = name
    fam.active = request.form.get("active") == "on"
    db.session.commit()
    flash("Familia actualizada.", "ok")
    return redirect(url_for("admin_families"))


@app.route("/admin/evento/nuevo", methods=["GET", "POST"])
@admin_required
def new_event():
    families = Family.query.filter_by(active=True).order_by(Family.name).all()
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:120]
        try:
            d1 = date.fromisoformat(request.form["start_date"])
            d2 = date.fromisoformat(request.form["end_date"])
        except (KeyError, ValueError):
            flash("Fechas inválidas.", "error")
            return render_template("admin_event_new.html", families=families)
        fids = request.form.getlist("families")
        if not name:
            flash("Ingresa un nombre para el evento.", "error")
        elif d2 < d1:
            flash("La fecha de término no puede ser anterior al inicio.", "error")
        elif not fids:
            flash("Selecciona al menos una familia participante.", "error")
        else:
            event = Event(name=name, start_date=d1, end_date=d2, status="open")
            db.session.add(event)
            db.session.flush()
            for fid in fids:
                db.session.add(
                    Participation(event_id=event.id, family_id=int(fid))
                )
            db.session.commit()
            flash("Evento creado.", "ok")
            return redirect(url_for("event_detail", eid=event.id))
        return render_template("admin_event_new.html", families=families)
    return render_template("admin_event_new.html", families=families)


@app.route("/admin/evento/<int:eid>/cerrar", methods=["POST"])
@admin_required
def close_event(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    event.status = "closed"
    db.session.commit()
    flash("Evento cerrado. La liquidación ya está disponible para todos.", "ok")
    return redirect(url_for("settlement", eid=eid))


@app.route("/admin/evento/<int:eid>/reabrir", methods=["POST"])
@admin_required
def reopen_event(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    event.status = "open"
    db.session.commit()
    flash("Evento reabierto para edición.", "ok")
    return redirect(url_for("event_detail", eid=eid))


@app.route("/admin/evento/<int:eid>/eliminar", methods=["POST"])
@admin_required
def delete_event(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)
    # Cascades to this event's participations, attendances and expenses.
    db.session.delete(event)
    db.session.commit()
    flash("Evento eliminado.", "ok")
    return redirect(url_for("index"))


@app.route("/admin/evento/<int:eid>/participantes", methods=["POST"])
@admin_required
def update_participants(eid):
    event = db.session.get(Event, eid)
    if not event:
        abort(404)

    valid_ids = {f.id for f in Family.query.all()}
    desired = {int(x) for x in request.form.getlist("families") if x.isdigit()}
    desired &= valid_ids
    if not desired:
        flash("El evento debe tener al menos una familia participante.", "error")
        return redirect(url_for("event_detail", eid=eid))

    current = {
        p.family_id: p for p in Participation.query.filter_by(event_id=eid).all()
    }

    for fid in desired - set(current):
        db.session.add(Participation(event_id=eid, family_id=fid))

    removed = 0
    for fid in set(current) - desired:
        # Drop the family's data for THIS event so nothing is orphaned.
        Attendance.query.filter_by(event_id=eid, family_id=fid).delete()
        Expense.query.filter_by(event_id=eid, family_id=fid).delete()
        db.session.delete(current[fid])
        removed += 1

    db.session.commit()
    msg = "Participantes actualizados."
    if removed:
        msg += f" Se quitaron {removed} familia(s) junto con sus datos en este evento."
    flash(msg, "ok")
    return redirect(url_for("event_detail", eid=eid))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
