from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from models import (
    Annotation, AnnotationStatus, Sample, SampleStatus,
    Project, Task, TaskSample, TaskStatus
)
from schemas import AnnotationCreate, AnnotationSubmit
from services.consistency_service import check_annotation_consistency


def validate_annotation_permission(
    db: Session,
    annotator_id: int,
    sample_id: int,
    task_id: Optional[int] = None,
    allow_rework: bool = False,
) -> Tuple[bool, str, dict]:
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        return False, "样本不存在", {"sample_id": sample_id}

    result_context = {
        "sample_id": sample_id,
        "project_id": sample.project_id,
    }

    if task_id is not None:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return False, "任务不存在", {"task_id": task_id, **result_context}

        result_context["task_project_id"] = task.project_id
        result_context["task_assignee_id"] = task.assignee_id

        if task.project_id != sample.project_id:
            return False, (
                f"项目不一致：任务属于项目{task.project_id}，"
                f"但样本属于项目{sample.project_id}"
            ), result_context

        if task.assignee_id != annotator_id:
            return False, (
                f"任务归属不一致：任务{task_id}分配给标注员{task.assignee_id}，"
                f"当前标注员是{annotator_id}"
            ), result_context

        if task.status in [TaskStatus.COMPLETED]:
            return False, f"任务{task_id}已完成，无法继续提交标注", result_context

        task_sample = (
            db.query(TaskSample)
            .filter(
                TaskSample.task_id == task_id,
                TaskSample.sample_id == sample_id,
            )
            .first()
        )
        if not task_sample:
            return False, (
                f"样本{sample_id}不在任务{task_id}的样本列表中，"
                f"标注员只能标注自己领取到的任务样本"
            ), result_context

    if not allow_rework:
        existing_ann = (
            db.query(Annotation)
            .filter(
                Annotation.sample_id == sample_id,
                Annotation.annotator_id == annotator_id,
                Annotation.status.in_([
                    AnnotationStatus.DRAFT,
                    AnnotationStatus.SUBMITTED,
                    AnnotationStatus.APPROVED,
                    AnnotationStatus.CONFLICT,
                ])
            )
            .first()
        )
        if existing_ann:
            return False, (
                f"标注员{annotator_id}已提交过样本{sample_id}的标注"
                f"(状态:{existing_ann.status.value})，不允许重复提交"
            ), {**result_context, "existing_annotation_id": existing_ann.id}

    return True, "权限校验通过", result_context


def create_annotation(
    db: Session,
    annotator_id: int,
    annotation: AnnotationCreate,
    task_id: Optional[int] = None,
    allow_rework: bool = False,
) -> Tuple[Optional[Annotation], Optional[str]]:
    is_valid, error_msg, ctx = validate_annotation_permission(
        db=db,
        annotator_id=annotator_id,
        sample_id=annotation.sample_id,
        task_id=task_id if task_id is not None else annotation.task_id,
        allow_rework=allow_rework,
    )
    if not is_valid:
        return None, f"[PERMISSION_DENIED] {error_msg}"

    sample = db.query(Sample).filter(Sample.id == annotation.sample_id).first()
    project_id = sample.project_id

    db_annotation = Annotation(
        project_id=project_id,
        sample_id=annotation.sample_id,
        annotator_id=annotator_id,
        task_id=annotation.task_id,
        content=annotation.content,
        time_spent_seconds=annotation.time_spent_seconds,
        comment=annotation.comment,
    )

    if sample.status in [SampleStatus.ASSIGNED, SampleStatus.PENDING, SampleStatus.REJECTED]:
        sample.status = SampleStatus.ANNOTATING

    db.add(db_annotation)
    db.commit()
    db.refresh(db_annotation)
    return db_annotation, None


def get_annotation(db: Session, annotation_id: int) -> Optional[Annotation]:
    return db.query(Annotation).filter(Annotation.id == annotation_id).first()


def get_annotations(
    db: Session,
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    annotator_id: Optional[int] = None,
    task_id: Optional[int] = None,
    status: Optional[AnnotationStatus] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Annotation]:
    query = db.query(Annotation)
    if project_id:
        query = query.filter(Annotation.project_id == project_id)
    if sample_id:
        query = query.filter(Annotation.sample_id == sample_id)
    if annotator_id:
        query = query.filter(Annotation.annotator_id == annotator_id)
    if task_id:
        query = query.filter(Annotation.task_id == task_id)
    if status:
        query = query.filter(Annotation.status == status)
    return query.order_by(Annotation.created_at.desc()).offset(skip).limit(limit).all()


def count_annotations(
    db: Session,
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    annotator_id: Optional[int] = None,
    status: Optional[AnnotationStatus] = None,
) -> int:
    query = db.query(Annotation)
    if project_id:
        query = query.filter(Annotation.project_id == project_id)
    if sample_id:
        query = query.filter(Annotation.sample_id == sample_id)
    if annotator_id:
        query = query.filter(Annotation.annotator_id == annotator_id)
    if status:
        query = query.filter(Annotation.status == status)
    return query.count()


def get_sample_annotations(db: Session, sample_id: int) -> List[Annotation]:
    return (
        db.query(Annotation)
        .filter(Annotation.sample_id == sample_id)
        .order_by(Annotation.created_at.asc())
        .all()
    )


def submit_annotation(
    db: Session,
    annotation_id: int,
    submission: AnnotationSubmit,
    submitter_id: Optional[int] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    annotation = get_annotation(db, annotation_id)
    if not annotation:
        return None, "标注不存在"

    if submitter_id is not None and annotation.annotator_id != submitter_id:
        return None, (
            f"[PERMISSION_DENIED] 标注{annotation_id}的归属标注员是"
            f"{annotation.annotator_id}，提交人{submitter_id}无权提交"
        )

    if annotation.task_id is not None:
        task = db.query(Task).filter(Task.id == annotation.task_id).first()
        if task:
            if task.status == TaskStatus.COMPLETED:
                return None, (
                    f"关联任务{task.id}已完成，无法继续提交标注"
                )
            if submitter_id is not None and task.assignee_id != submitter_id:
                return None, (
                    f"[PERMISSION_DENIED] 任务{task.id}的归属人是"
                    f"{task.assignee_id}，提交人{submitter_id}无权操作"
                )

    sample = db.query(Sample).filter(Sample.id == annotation.sample_id).first()
    if sample and sample.project_id != annotation.project_id:
        return None, "数据异常：样本与标注项目不一致，拒绝提交以防脏数据"

    annotation.content = submission.content
    annotation.time_spent_seconds = submission.time_spent_seconds
    annotation.comment = submission.comment
    annotation.status = AnnotationStatus.SUBMITTED
    annotation.version += 1

    sample = db.query(Sample).filter(Sample.id == annotation.sample_id).first()
    if sample:
        sample.status = SampleStatus.SUBMITTED

    from crud.crud_tasks import mark_task_sample_completed
    if annotation.task_id:
        mark_task_sample_completed(db, annotation.task_id, annotation.sample_id)

    db.commit()
    db.refresh(annotation)

    consistency_result = process_sample_consistency(db, annotation.sample_id)

    return {
        'annotation': annotation,
        'consistency': consistency_result,
    }, None


def process_sample_consistency(db: Session, sample_id: int) -> dict:
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        return {'processed': False, 'error': 'sample not found'}

    project = db.query(Project).filter(Project.id == sample.project_id).first()
    if not project:
        return {'processed': False, 'error': 'project not found'}

    annotations = (
        db.query(Annotation)
        .filter(
            Annotation.sample_id == sample_id,
            Annotation.status.in_([
                AnnotationStatus.SUBMITTED,
                AnnotationStatus.APPROVED,
                AnnotationStatus.CONFLICT,
            ])
        )
        .all()
    )

    required_count = project.required_annotators
    if len(annotations) < required_count:
        return {
            'processed': False,
            'message': f'Waiting for more annotations. Have {len(annotations)}, need {required_count}',
            'current_count': len(annotations),
            'required_count': required_count,
        }

    threshold = project.consistency_threshold
    from crud.crud_projects import get_label_specs
    label_specs = get_label_specs(db, project.id)

    consistency_result = check_annotation_consistency(
        annotations=annotations,
        threshold=threshold,
        label_specs=label_specs,
    )

    sample.consistency_score = consistency_result['consistency_score']
    sample.consistency_level = consistency_result['consistency_level']

    result = {
        'processed': True,
        'sample_id': sample_id,
        'consistency_score': consistency_result['consistency_score'],
        'consistency_level': consistency_result['consistency_level'].value if hasattr(
            consistency_result['consistency_level'], 'value'
        ) else str(consistency_result['consistency_level']),
        'is_consistent': consistency_result['is_consistent'],
        'conflict_fields': consistency_result['conflict_fields'],
        'annotation_count': len(annotations),
    }

    if consistency_result['is_consistent']:
        sample.status = SampleStatus.APPROVED
        sample.final_annotation = consistency_result['majority_annotation']

        for ann in annotations:
            ann.status = AnnotationStatus.APPROVED

        result['action'] = 'auto_approved'
        result['final_annotation'] = consistency_result['majority_annotation']
    else:
        sample.status = SampleStatus.CONFLICT

        for ann in annotations:
            ann.status = AnnotationStatus.CONFLICT

        from models import ConflictRecord
        annotator_ids = [ann.annotator_id for ann in annotations]

        existing_conflict = (
            db.query(ConflictRecord)
            .filter(
                ConflictRecord.sample_id == sample_id,
                ConflictRecord.resolved == False,
            )
            .first()
        )

        if not existing_conflict:
            conflict = ConflictRecord(
                project_id=sample.project_id,
                sample_id=sample_id,
                involved_annotator_ids=annotator_ids,
                conflict_fields=consistency_result['conflict_fields'],
                consistency_score=consistency_result['consistency_score'],
            )
            db.add(conflict)
            db.flush()

            from models import UserRole, ReviewTask as RT, User

            quality_checkers = (
                db.query(User)
                .filter(
                    User.role.in_([UserRole.QUALITY_CHECKER, UserRole.ADMIN]),
                    User.is_active == True,
                )
                .all()
            )

            created_review_tasks = []
            for qc in quality_checkers:
                existing_rt = (
                    db.query(RT)
                    .filter(
                        RT.conflict_id == conflict.id,
                        RT.assignee_id == qc.id,
                    )
                    .first()
                )
                if not existing_rt:
                    rt = RT(
                        project_id=sample.project_id,
                        conflict_id=conflict.id,
                        sample_id=sample_id,
                        assignee_id=qc.id,
                    )
                    db.add(rt)
                    created_review_tasks.append({
                        'review_task_id': None,
                        'assignee_id': qc.id,
                        'assignee_name': qc.display_name,
                    })

            if created_review_tasks:
                db.flush()
                for i, rt_obj in enumerate(created_review_tasks):
                    created_review_tasks[i]['review_task_id'] = rt_obj.get('review_task_id')

            result['action'] = 'conflict_created'
            result['conflict_created'] = True
            result['review_tasks_created'] = len(created_review_tasks)
            result['review_tasks'] = created_review_tasks
            result['assigned_quality_checkers'] = [qc.display_name for qc in quality_checkers]
        else:
            result['action'] = 'conflict_exists'
            result['conflict_created'] = False
            result['review_tasks_created'] = 0

    db.commit()
    return result


def delete_annotation(db: Session, annotation_id: int) -> bool:
    annotation = get_annotation(db, annotation_id)
    if not annotation:
        return False
    db.delete(annotation)
    db.commit()
    return True
