from __future__ import annotations

import asyncio  # noqa: F401  (kept for symmetry with recognition router)
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.deps import client_ip, current_user, require_admin
from app.core.errors import AppError
from app.core.timeutil import utc_now
from app.database.base import get_db
from app.models import Department, FaceEmbedding, Person, PersonStatus, User
from app.schemas.common import make_page
from app.schemas.person import EnrollmentResult, PersonCreate, PersonOut, PersonUpdate
from app.services import audit_service, enrollment_service
from app.services.embedding_cache import get_cache
from app.services.face_detection import ModelUnavailableError

router = APIRouter(tags=["people"])


def _dept(db: Session, name: str | None) -> Department | None:
    if not name:
        return None
    d = db.scalar(select(Department).where(func.lower(Department.name) == name.lower()))
    if d is None:
        d = Department(name=name)
        db.add(d)
        db.flush()
    return d


def _out(db: Session, p: Person, counts: dict[int, int] | None = None) -> dict:
    n = counts.get(p.id, 0) if counts is not None else enrollment_service.sample_count(db, p.id)
    return {
        "id": p.id, "person_code": p.person_code, "full_name": p.full_name, "email": p.email,
        "department": p.department.name if p.department else None, "role": p.role, "status": p.status,
        "registered_at": p.registered_at, "consent_at": p.consent_at, "anonymized": p.anonymized,
        "enrolled_samples": n, "enrollment_status": enrollment_service.enrollment_status(n),
    }


def _get(db: Session, person_id: int) -> Person:
    p = db.scalar(select(Person).options(joinedload(Person.department)).where(Person.id == person_id))
    if p is None:
        raise AppError(404, "not_found", "Person not found")
    return p


@router.get("/departments", response_model=list[str])
def departments(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Department.name).order_by(Department.name)))


@router.get("/people")
def list_people(
    q: str | None = None, department: str | None = None, role: str | None = None,
    status: str | None = None, enrollment: str | None = Query(None, pattern="^(enrolled|partial|not_enrolled)$"),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Person).options(joinedload(Person.department)).where(Person.anonymized.is_(False))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Person.full_name).like(like), func.lower(Person.person_code).like(like)))
    if department:
        stmt = stmt.join(Department, isouter=True).where(func.lower(Department.name) == department.lower())
    if role:
        stmt = stmt.where(Person.role == role)
    if status:
        stmt = stmt.where(Person.status == status)
    counts_sq = select(FaceEmbedding.person_id, func.count(FaceEmbedding.id).label("n")).group_by(
        FaceEmbedding.person_id).subquery()
    if enrollment:
        stmt = stmt.outerjoin(counts_sq, counts_sq.c.person_id == Person.id)
        n = func.coalesce(counts_sq.c.n, 0)
        min_n = get_settings().min_enroll_images
        stmt = stmt.where({"enrolled": n >= min_n, "partial": (n > 0) & (n < min_n), "not_enrolled": n == 0}[enrollment])
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    people = db.scalars(stmt.order_by(Person.full_name, Person.id).offset((page - 1) * page_size)
                        .limit(page_size)).unique().all()
    counts = dict(db.execute(select(FaceEmbedding.person_id, func.count(FaceEmbedding.id))
                             .where(FaceEmbedding.person_id.in_([p.id for p in people]))
                             .group_by(FaceEmbedding.person_id)).all()) if people else {}
    return make_page([_out(db, p, counts) for p in people], total, page, page_size)


@router.post("/people", response_model=PersonOut, status_code=201)
def create_person(body: PersonCreate, request: Request, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    if db.scalar(select(Person.id).where(func.lower(Person.person_code) == body.person_code.lower())):
        raise AppError(409, "duplicate_person_id", f"Person ID '{body.person_code}' is already registered")
    if body.email and db.scalar(select(Person.id).where(func.lower(Person.email) == body.email.lower())):
        raise AppError(409, "duplicate_email", "A person with this email is already registered")
    person = Person(person_code=body.person_code, full_name=body.full_name, email=body.email, role=body.role,
                    status=body.status, department=_dept(db, body.department))
    db.add(person)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "duplicate_person_id", "Person ID or email already registered") from None
    audit_service.log(db, "person_create", admin, "person", person.id, {"person_code": person.person_code},
                      client_ip(request))
    return _out(db, _get(db, person.id))


@router.get("/people/{person_id}", response_model=PersonOut)
def get_person(person_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return _out(db, _get(db, person_id))


@router.put("/people/{person_id}", response_model=PersonOut)
def update_person(person_id: int, body: PersonUpdate, request: Request, admin: User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    p = _get(db, person_id)
    if p.anonymized:
        raise AppError(409, "anonymized", "This person has been deleted and cannot be edited")
    changes: dict = {}
    if body.full_name:
        p.full_name = " ".join(body.full_name.split())
        changes["full_name"] = True
    if body.clear_email:
        p.email = None
    elif body.email:
        clash = db.scalar(select(Person.id).where(func.lower(Person.email) == body.email.lower(), Person.id != p.id))
        if clash:
            raise AppError(409, "duplicate_email", "A person with this email is already registered")
        p.email = body.email
    if body.clear_department:
        p.department = None
    elif body.department:
        p.department = _dept(db, body.department)
    if body.role:
        p.role = body.role
    status_changed = False
    if body.status and body.status != p.status:
        p.status, status_changed = body.status, True
        changes["status"] = body.status.value
    db.commit()
    if status_changed:
        get_cache().refresh(db)   # disabled people must stop matching immediately
    audit_service.log(db, "person_update", admin, "person", p.id, changes, client_ip(request))
    return _out(db, _get(db, p.id))


@router.delete("/people/{person_id}", status_code=200)
def delete_person(person_id: int, request: Request,
                  purge_attendance: bool = Query(False, description="Also delete this person's attendance history"),
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Biometric deletion workflow.

    Always: every face template is deleted and the live gallery is refreshed.
    purge_attendance=false (default): the person is anonymised (name/ID/email removed, account disabled) so
        historical attendance totals stay correct without identifying anyone.
    purge_attendance=true: the person row and all their attendance records are deleted."""
    p = _get(db, person_id)
    code = p.person_code
    templates = db.query(FaceEmbedding).filter(FaceEmbedding.person_id == p.id).delete()
    if purge_attendance:
        db.delete(p)
    else:
        p.full_name, p.person_code, p.email = f"Deleted person #{p.id}", f"deleted-{p.id}", None
        p.status, p.anonymized, p.consent_at, p.department_id = PersonStatus.disabled, True, None, None
    db.commit()
    get_cache().refresh(db)
    audit_service.log(db, "person_delete", admin, "person", person_id,
                      {"person_code": code, "templates_deleted": templates, "purge_attendance": purge_attendance},
                      client_ip(request))
    return {"deleted_templates": templates, "mode": "purged" if purge_attendance else "anonymised"}


@router.delete("/people/{person_id}/biometrics", status_code=200)
def delete_biometrics(person_id: int, request: Request, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    p = _get(db, person_id)
    n = enrollment_service.delete_biometrics(db, p)
    p.consent_at = None
    db.commit()
    audit_service.log(db, "biometrics_delete", admin, "person", p.id, {"templates_deleted": n}, client_ip(request))
    return {"deleted_templates": n}


# ---- enrolment -------------------------------------------------------------
def _read_uploads(files: list[UploadFile]) -> list[bytes]:
    s = get_settings()
    if not files:
        raise AppError(422, "no_files", "No images were uploaded")
    if len(files) > s.max_enroll_images * 2:
        raise AppError(422, "too_many_files", f"At most {s.max_enroll_images * 2} images per request")
    out = []
    for f in files:
        data = f.file.read(s.max_upload_bytes + 1)
        out.append(data)   # size/type validation happens in decode_image (per-image rejection)
    return out


def _do_enroll(db: Session, person_id: int, files: list[UploadFile], consent: bool, confirm_duplicate: bool,
               source: str, admin: User, request: Request) -> EnrollmentResult:
    p = _get(db, person_id)
    if p.anonymized:
        raise AppError(409, "anonymized", "This person has been deleted")
    if not consent:
        raise AppError(422, "consent_required", "Confirm that the person has given consent to biometric enrolment")
    images = _read_uploads(files)
    try:
        out = enrollment_service.enroll(db, p, images, source, admin, confirm_duplicate)
    except ModelUnavailableError as exc:
        raise AppError(503, "model_unavailable", str(exc)) from exc
    except ValueError as exc:
        raise AppError(422, "invalid_request", str(exc)) from exc
    audit_service.log(db, "enroll" if out.saved else "enroll_rejected", admin, "person", p.id,
                      {"accepted": out.accepted, "rejected": len(out.rejected), "source": source,
                       "duplicates": [d["person_code"] for d in out.possible_duplicates]}, client_ip(request))
    n = enrollment_service.sample_count(db, p.id)
    result = EnrollmentResult(
        person_id=p.id, accepted=out.accepted, total_samples=n, enrollment_status=enrollment_service.enrollment_status(n),
        rejected=[{"index": r.index, "reason": r.reason, "code": r.code} for r in out.rejected],
        possible_duplicates=out.possible_duplicates, warnings=out.warnings)
    if out.possible_duplicates and not out.saved:
        raise AppError(409, "possible_duplicate", out.warnings[-1], result.model_dump())
    if not out.saved:
        raise AppError(422, "no_usable_images", "None of the images were usable", result.model_dump())
    return result


@router.post("/people/{person_id}/enroll", response_model=EnrollmentResult)
def enroll_webcam(person_id: int, request: Request, files: Annotated[list[UploadFile], File()],
                  consent: bool = Form(...), confirm_duplicate: bool = Form(False),
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Webcam captures (JPEG frames taken by the browser)."""
    return _do_enroll(db, person_id, files, consent, confirm_duplicate, "webcam", admin, request)


@router.post("/people/{person_id}/enroll-images", response_model=EnrollmentResult)
def enroll_upload(person_id: int, request: Request, files: Annotated[list[UploadFile], File()],
                  consent: bool = Form(...), confirm_duplicate: bool = Form(False),
                  admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Uploaded photographs (alternative to the webcam). Same validation as webcam enrolment."""
    return _do_enroll(db, person_id, files, consent, confirm_duplicate, "upload", admin, request)


@router.get("/people/{person_id}/enrollment-status")
def enrollment_status(person_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _get(db, person_id)
    n = enrollment_service.sample_count(db, p.id)
    s = get_settings()
    return {"person_id": p.id, "samples": n, "required": s.min_enroll_images, "max": s.max_enroll_images,
            "status": enrollment_service.enrollment_status(n), "consent_at": p.consent_at}
