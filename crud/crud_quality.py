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

    conflict_dict = {c.name: getattr(conflict, c.name) for c in conflict.__table__.columns}
    result = {
        'conflict': conflict_dict,
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

    rt_dict = {c.name: getattr(rt, c.name) for c in rt.__table__.columns}
    result = {
        'review_task': rt_dict,
        'conflict_resolved': False,
    }

    # ===== 先收集并同步同冲突其他 RT 为 completed =====
    other_rts_completed = 0
    all_rts = []
    if conflict:
        sibling_rts = (
            db.query(ReviewTask)
            .filter(ReviewTask.conflict_id == conflict.id)
            .all()
        )
        for srt in sibling_rts:
            if srt.id != rt.id and srt.status != TaskStatus.COMPLETED:
                srt.status = TaskStatus.COMPLETED
                srt.resolution_comment = (
                    submission.resolution_comment
                    or f"同冲突已由复核人{submission.checker_id}处理完成"
                )
                srt.resolution = submission.resolution
                other_rts_completed += 1

    # ===== 再解决冲突（内部会再次确认 RT 状态，不影响）=====
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
            result['conflict'] = resolved.get('conflict')
            result['sample_updated'] = resolved.get('sample_updated', False)

    # ===== 读取所有 RT 的最新状态转 dict =====
    if conflict:
        sibling_rts = (
            db.query(ReviewTask)
            .filter(ReviewTask.conflict_id == conflict.id)
            .all()
        )
        all_rts = [{c.name: getattr(srt, c.name) for c in srt.__table__.columns} for srt in sibling_rts]

    # ===== 收集样本最终状态 =====
    sample_dict = None
    if rt.sample_id:
        from crud import crud_samples
        s = crud_samples.get_sample(db, rt.sample_id)
        if s:
            sample_dict = {}
            for c in s.__table__.columns:
                col = c.name
                if col == 'metadata':
                    sample_dict[col] = s.sample_metadata
                else:
                    sample_dict[col] = getattr(s, col)

    # ===== 收集该样本所有标注状态 =====
    annotations = []
    if rt.sample_id:
        from crud import crud_annotations as _ca
        anns = _ca.get_sample_annotations(db, rt.sample_id)
        for a in anns:
            annotations.append({c.name: getattr(a, c.name) for c in a.__table__.columns})

    result['sample'] = sample_dict
    result['annotations'] = annotations
    result['annotation_count'] = len(annotations)
    result['all_conflict_review_tasks'] = all_rts
    result['other_review_tasks_synced_completed'] = other_rts_completed

    db.commit()
    db.refresh(rt)
    rt_dict2 = {c.name: getattr(rt, c.name) for c in rt.__table__.columns}
    result['review_task'] = rt_dict2
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
    new_annotation_content: Optional[dict] = None,
    rework_annotator_id: Optional[int] = None,
    time_spent_seconds: Optional[int] = None,
) -> Optional[dict]:
    rework = get_rework(db, rework_id)
    if not rework:
        return None

    rework.status = TaskStatus.COMPLETED
    rework.completed_at = datetime.utcnow()

    # 如果传了新内容，优先创建一条新的 Annotation
    new_ann = None
    if new_annotation_content is not None and rework.sample_id and rework.project_id:
        target_annotator = (
            rework_annotator_id
            or rework.rework_annotator_id
            or rework.original_annotator_id
        )
        from schemas import AnnotationCreate
        from crud import crud_annotations
        ann_create = AnnotationCreate(
            sample_id=rework.sample_id,
            task_id=None,
            content=new_annotation_content,
            time_spent_seconds=time_spent_seconds or 0,
        )
        created_tuple = crud_annotations.create_annotation(
            db=db, annotator_id=target_annotator, annotation=ann_create,
            task_id=None, allow_rework=True,
        )
        if isinstance(created_tuple, tuple):
            new_ann = created_tuple[0]
        else:
            new_ann = created_tuple

        if new_ann:
            from models import AnnotationStatus
            try:
                new_ann.status = AnnotationStatus.SUBMITTED
                new_ann.version = (new_ann.version or 0) + 1
            except Exception:
                pass
            rework.new_annotation_id = new_ann.id
    elif new_annotation_id:
        from models import Annotation, AnnotationStatus
        new_ann = db.query(Annotation).filter(
            Annotation.id == new_annotation_id
        ).first()
        if new_ann:
            new_ann.status = AnnotationStatus.SUBMITTED
            try:
                new_ann.version = (new_ann.version or 0) + 1
            except Exception:
                pass
            rework.new_annotation_id = new_ann.id

    consistency_result = None
    if rework.sample_id:
        from crud.crud_annotations import process_sample_consistency
        consistency_result = process_sample_consistency(db, rework.sample_id)

    db.commit()
    db.refresh(rework)

    rework_dict = {c.name: getattr(rework, c.name) for c in rework.__table__.columns}

    new_ann_dict = None
    if new_ann:
        new_ann_dict = {c.name: getattr(new_ann, c.name) for c in new_ann.__table__.columns}

    sample_dict = None
    if rework.sample_id:
        from crud import crud_samples
        s = crud_samples.get_sample(db, rework.sample_id)
        if s:
            sample_dict = {}
            for c in s.__table__.columns:
                col = c.name
                if col == 'metadata':
                    sample_dict[col] = s.sample_metadata
                else:
                    sample_dict[col] = getattr(s, col)

    return {
        "rework": rework_dict,
        "new_annotation": new_ann_dict,
        "sample": sample_dict,
        "consistency_checked": consistency_result is not None,
        "consistency_result": consistency_result,
    }


def batch_process_quality_checks(
    db: Session,
    quality_check_ids: List[int],
    checker_id: int,
    action: str,
    common_comment: Optional[str] = None,
    common_quality_score: Optional[float] = None,
    rework_reason: Optional[str] = None,
    rework_target_annotator_id: Optional[int] = None,
) -> dict:
    if action not in ['approve', 'reject', 'rework']:
        raise ValueError(f"无效的操作：{action}。可选值：approve/reject/rework")

    processed = 0
    failed = 0
    results = []
    rework_ids_created = []
    sample_ids_touched = set()
    annotation_ids_touched = set()

    target_qc_status = {
        'approve': QualityStatus.PASSED,
        'reject': QualityStatus.FAILED,
        'rework': QualityStatus.NEEDS_REWORK,
    }[action]

    for qc_id in quality_check_ids:
        try:
            qc = get_quality_check(db, qc_id)
            if not qc:
                results.append({"quality_check_id": qc_id, "success": False, "error": "质检记录不存在"})
                failed += 1
                continue

            if qc.status != QualityStatus.PENDING:
                results.append({
                    "quality_check_id": qc_id,
                    "success": False,
                    "error": f"质检记录状态已为 {qc.status.value}，不能重复处理",
                })
                failed += 1
                continue

            qc.status = target_qc_status
            if common_quality_score is not None:
                qc.quality_score = common_quality_score
            if common_comment:
                qc.comment = common_comment
            qc.checker_id = checker_id

            sample = db.query(Sample).filter(Sample.id == qc.sample_id).first() if qc.sample_id else None
            if sample:
                sample_ids_touched.add(sample.id)

            annotation = None
            if qc.annotation_id:
                annotation = db.query(Annotation).filter(Annotation.id == qc.annotation_id).first()
                if annotation:
                    annotation_ids_touched.add(annotation.id)

            # 如无指定 annotation，尝试从 sample 下找最近一条 SUBMITTED 标注
            if annotation is None and qc.sample_id:
                annotation = (
                    db.query(Annotation)
                    .filter(
                        Annotation.sample_id == qc.sample_id,
                        Annotation.status.in_([
                            AnnotationStatus.SUBMITTED,
                            AnnotationStatus.APPROVED,
                            AnnotationStatus.REJECTED,
                        ]),
                    )
                    .order_by(Annotation.created_at.desc())
                    .first()
                )
                if annotation:
                    annotation_ids_touched.add(annotation.id)

            if action == 'approve':
                if annotation:
                    annotation.status = AnnotationStatus.APPROVED
                if sample:
                    sample.status = SampleStatus.APPROVED
                    from models import ConsistencyLevel
                    sample.consistency_score = 1.0
                    sample.consistency_level = ConsistencyLevel.HIGH
                    if annotation:
                        sample.final_annotation = annotation.content
                results.append({"quality_check_id": qc_id, "success": True, "action": "passed"})
                processed += 1

            elif action == 'reject':
                if annotation:
                    annotation.status = AnnotationStatus.REJECTED
                if sample:
                    sample.status = SampleStatus.REJECTED
                results.append({"quality_check_id": qc_id, "success": True, "action": "failed"})
                processed += 1

            elif action == 'rework':
                # 确定返工对象标注员
                original_annotator_id = None
                if annotation:
                    original_annotator_id = annotation.annotator_id
                elif rework_target_annotator_id:
                    original_annotator_id = rework_target_annotator_id
                else:
                    # 从该样本下任意提交过的标注里取一个标注员
                    any_ann = (
                        db.query(Annotation)
                        .filter(Annotation.sample_id == qc.sample_id)
                        .order_by(Annotation.created_at.desc())
                        .first()
                    )
                    if any_ann:
                        original_annotator_id = any_ann.annotator_id

                if original_annotator_id is None and not rework_target_annotator_id:
                    results.append({
                        "quality_check_id": qc_id,
                        "success": False,
                        "error": "找不到可返工的标注员：该样本下没有任何标注记录，请指定 rework_target_annotator_id",
                    })
                    failed += 1
                    continue

                if annotation:
                    annotation.status = AnnotationStatus.REJECTED
                if sample:
                    sample.status = SampleStatus.ANNOTATING

                final_original_id = original_annotator_id or rework_target_annotator_id
                rework_create = ReworkRecordCreate(
                    project_id=qc.project_id,
                    sample_id=qc.sample_id,
                    quality_check_id=qc.id,
                    original_annotator_id=final_original_id,
                    rework_annotator_id=(
                        rework_target_annotator_id
                        if rework_target_annotator_id is not None
                        else final_original_id
                    ),
                    reason=rework_reason or "质检不合格，需要返工",
                    issue_fields=None,
                )
                rework_record = create_rework(db, rework_create)
                rework_id = None
                if rework_record:
                    rework_id = rework_record.id
                    rework_ids_created.append(rework_id)

                results.append({
                    "quality_check_id": qc_id,
                    "success": True,
                    "action": "rework_created",
                    "rework_id": rework_id,
                    "original_annotator_id": final_original_id,
                })
                processed += 1

        except Exception as e:
            db.rollback()
            results.append({"quality_check_id": qc_id, "success": False, "error": str(e)})
            failed += 1
            continue

    db.commit()

    return {
        "action": action,
        "total_input": len(quality_check_ids),
        "processed": processed,
        "failed": failed,
        "details": results,
        "rework_ids_created": rework_ids_created,
        "sample_ids_updated": sorted(list(sample_ids_touched)),
        "annotation_ids_updated": sorted(list(annotation_ids_touched)),
    }
