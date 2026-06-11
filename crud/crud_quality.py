from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from models import (
    QualityCheck, QualityStatus, ConflictRecord, ReviewTask,
    ReworkRecord, Sample, SampleStatus, TaskStatus, Annotation,
    AnnotationStatus, Project, User
)
from schemas import (
    QualityCheckCreate, QualityCheckSubmit, ReworkRecordCreate,
    ConflictResolve, ReviewTaskSubmit
)
from services.sampling_service import sample_quality_checks


def create_quality_check(db: Session, qc: QualityCheckCreate) -> QualityCheck:
    db_qc = QualityCheck(
        project_id=qc.project_id,
        sample_id=qc.sample_id,
        checker_id=qc.checker_id,
        annotation_id=qc.annotation_id,
        comment=qc.comment,
    )
    db.add(db_qc)
    db.commit()
    db.refresh(db_qc)
    return db_qc


def get_quality_check(db: Session, qc_id: int) -> Optional[QualityCheck]:
    return db.query(QualityCheck).filter(QualityCheck.id == qc_id).first()


def get_quality_checks(
    db: Session,
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    checker_id: Optional[int] = None,
    status: Optional[QualityStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[QualityCheck]:
    query = db.query(QualityCheck)
    if project_id:
        query = query.filter(QualityCheck.project_id == project_id)
    if sample_id:
        query = query.filter(QualityCheck.sample_id == sample_id)
    if checker_id:
        query = query.filter(QualityCheck.checker_id == checker_id)
    if status:
        query = query.filter(QualityCheck.status == status)
    return query.order_by(QualityCheck.created_at.desc()).offset(skip).limit(limit).all()


def submit_quality_check(
    db: Session,
    qc_id: int,
    submission: QualityCheckSubmit,
) -> Optional[dict]:
    qc = get_quality_check(db, qc_id)
    if not qc:
        return None

    qc.status = submission.status
    qc.quality_score = submission.quality_score
    qc.error_fields = submission.error_fields
    qc.comment = submission.comment

    sample = db.query(Sample).filter(Sample.id == qc.sample_id).first()

    result = {
        'quality_check': qc,
        'sample_updated': False,
        'rework_created': False,
    }

    if submission.status == QualityStatus.PASSED:
        if sample:
            sample.status = SampleStatus.APPROVED
        result['sample_updated'] = True
    elif submission.status == QualityStatus.FAILED:
        if sample:
            sample.status = SampleStatus.REJECTED
        result['sample_updated'] = True
    elif submission.status == QualityStatus.NEEDS_REWORK:
        if sample:
            sample.status = SampleStatus.REJECTED

        ann = None
        if qc.annotation_id:
            ann = db.query(Annotation).filter(Annotation.id == qc.annotation_id).first()
        elif sample:
            ann = (
                db.query(Annotation)
                .filter(Annotation.sample_id == sample.id)
                .order_by(Annotation.created_at.desc())
                .first()
            )

        if ann:
            original_annotator_id = ann.annotator_id
            rework = ReworkRecord(
                project_id=qc.project_id,
                sample_id=qc.sample_id,
                quality_check_id=qc.id,
                original_annotator_id=original_annotator_id,
                rework_annotator_id=original_annotator_id,
                reason=submission.comment or '质检不通过，需要返工',
                issue_fields=submission.error_fields,
            )
            db.add(rework)
            result['rework_created'] = True
            result['rework_id'] = rework.id

            ann.status = AnnotationStatus.REJECTED

    db.commit()
    db.refresh(qc)
    return result


def create_quality_check_batch(
    db: Session,
    project_id: int,
    checker_id: int,
    sample_count: Optional[int] = None,
    sample_rate: Optional[float] = None,
) -> List[QualityCheck]:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return []

    rate = sample_rate if sample_rate is not None else project.quality_sample_rate

    candidate_samples = (
        db.query(Sample)
        .filter(
            Sample.project_id == project_id,
            Sample.status.in_([
                SampleStatus.APPROVED,
                SampleStatus.SUBMITTED,
                SampleStatus.CONFLICT,
            ])
        )
        .all()
    )

    if not candidate_samples:
        return []

    sampled = sample_quality_checks(
        samples=candidate_samples,
        sample_rate=rate,
        min_samples=sample_count or 1,
        max_samples=sample_count,
        prioritize_conflict=True,
    )

    qcs = []
    for sample in sampled:
        existing = (
            db.query(QualityCheck)
            .filter(
                QualityCheck.sample_id == sample.id,
                QualityCheck.checker_id == checker_id,
                QualityCheck.status == QualityStatus.PENDING,
            )
            .first()
        )
        if existing:
            continue

        qc = QualityCheck(
            project_id=project_id,
            sample_id=sample.id,
            checker_id=checker_id,
            is_sampled=True,
        )
        db.add(qc)
        qcs.append(qc)

    db.commit()
    for qc in qcs:
        db.refresh(qc)
    return qcs


def get_conflict(db: Session, conflict_id: int) -> Optional[ConflictRecord]:
    return db.query(ConflictRecord).filter(ConflictRecord.id == conflict_id).first()


def get_conflicts(
    db: Session,
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[ConflictRecord]:
    query = db.query(ConflictRecord)
    if project_id:
        query = query.filter(ConflictRecord.project_id == project_id)
    if sample_id:
        query = query.filter(ConflictRecord.sample_id == sample_id)
    if resolved is not None:
        query = query.filter(ConflictRecord.resolved == resolved)
    return query.order_by(ConflictRecord.created_at.desc()).offset(skip).limit(limit).all()


def count_conflicts(
    db: Session,
    project_id: Optional[int] = None,
    resolved: Optional[bool] = None,
) -> int:
    query = db.query(ConflictRecord)
    if project_id:
        query = query.filter(ConflictRecord.project_id == project_id)
    if resolved is not None:
        query = query.filter(ConflictRecord.resolved == resolved)
    return query.count()


def resolve_conflict(
    db: Session,
    conflict_id: int,
    resolution: ConflictResolve,
) -> Optional[dict]:
    conflict = get_conflict(db, conflict_id)
    if not conflict:
        return None

    conflict.resolved = True
    conflict.resolver_id = resolution.resolver_id
    conflict.resolved_at = datetime.utcnow()
    conflict.resolution_note = resolution.resolution_note

    sample = db.query(Sample).filter(Sample.id == conflict.sample_id).first()

    result = {
        'conflict': conflict,
        'sample_updated': False,
    }

    if sample:
        sample.status = SampleStatus.APPROVED
        sample.final_annotation = resolution.final_annotation
        sample.consistency_score = 1.0
        from models import ConsistencyLevel
        sample.consistency_level = ConsistencyLevel.HIGH
        result['sample_updated'] = True

    annotations = (
        db.query(Annotation)
        .filter(Annotation.sample_id == conflict.sample_id)
        .all()
    )
    for ann in annotations:
        ann.status = AnnotationStatus.APPROVED

    review_tasks = (
        db.query(ReviewTask)
        .filter(ReviewTask.conflict_id == conflict_id)
        .all()
    )
    for rt in review_tasks:
        rt.status = TaskStatus.COMPLETED

    db.commit()
    db.refresh(conflict)
    return result


def create_review_task(
    db: Session,
    conflict_id: int,
    assignee_id: int,
) -> Optional[ReviewTask]:
    conflict = get_conflict(db, conflict_id)
    if not conflict:
        return None

    rt = ReviewTask(
        project_id=conflict.project_id,
        conflict_id=conflict_id,
        sample_id=conflict.sample_id,
        assignee_id=assignee_id,
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)
    return rt


def get_review_task(db: Session, rt_id: int) -> Optional[ReviewTask]:
    return db.query(ReviewTask).filter(ReviewTask.id == rt_id).first()


def get_review_tasks(
    db: Session,
    project_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[ReviewTask]:
    query = db.query(ReviewTask)
    if project_id:
        query = query.filter(ReviewTask.project_id == project_id)
    if assignee_id:
        query = query.filter(ReviewTask.assignee_id == assignee_id)
    if status:
        query = query.filter(ReviewTask.status == status)
    return query.order_by(ReviewTask.created_at.desc()).offset(skip).limit(limit).all()


def submit_review_task(
    db: Session,
    rt_id: int,
    submission: ReviewTaskSubmit,
) -> Optional[dict]:
    rt = get_review_task(db, rt_id)
    if not rt:
        return None

    rt.resolution = submission.resolution
    rt.resolution_comment = submission.resolution_comment
    rt.status = TaskStatus.COMPLETED

    conflict = get_conflict(db, rt.conflict_id)

    result = {
        'review_task': rt,
        'conflict_resolved': False,
    }

    if conflict:
        resolve_data = ConflictResolve(
            resolver_id=submission.checker_id,
            resolution_note=submission.resolution_comment,
            final_annotation=submission.resolution,
        )
        resolved = resolve_conflict(db, conflict.id, resolve_data)
        if resolved:
            result['conflict_resolved'] = True
            result['resolution'] = resolved

    db.commit()
    db.refresh(rt)
    return result


def create_rework(db: Session, rework: ReworkRecordCreate) -> ReworkRecord:
    db_rework = ReworkRecord(
        project_id=rework.project_id,
        sample_id=rework.sample_id,
        quality_check_id=rework.quality_check_id,
        original_annotator_id=rework.original_annotator_id,
        rework_annotator_id=rework.rework_annotator_id or rework.original_annotator_id,
        reason=rework.reason,
        issue_fields=rework.issue_fields,
    )
    db.add(db_rework)

    sample = db.query(Sample).filter(Sample.id == rework.sample_id).first()
    if sample:
        sample.status = SampleStatus.ANNOTATING

    db.commit()
    db.refresh(db_rework)
    return db_rework


def get_rework(db: Session, rework_id: int) -> Optional[ReworkRecord]:
    return db.query(ReworkRecord).filter(ReworkRecord.id == rework_id).first()


def get_reworks(
    db: Session,
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    original_annotator_id: Optional[int] = None,
    rework_annotator_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[ReworkRecord]:
    query = db.query(ReworkRecord)
    if project_id:
        query = query.filter(ReworkRecord.project_id == project_id)
    if sample_id:
        query = query.filter(ReworkRecord.sample_id == sample_id)
    if original_annotator_id:
        query = query.filter(ReworkRecord.original_annotator_id == original_annotator_id)
    if rework_annotator_id:
        query = query.filter(ReworkRecord.rework_annotator_id == rework_annotator_id)
    if status:
        query = query.filter(ReworkRecord.status == status)
    return query.order_by(ReworkRecord.created_at.desc()).offset(skip).limit(limit).all()


def complete_rework(
    db: Session,
    rework_id: int,
    new_annotation_id: Optional[int] = None,
) -> Optional[ReworkRecord]:
    rework = get_rework(db, rework_id)
    if not rework:
        return None

    rework.status = TaskStatus.COMPLETED
    rework.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(rework)
    return rework
