from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session

from models import Annotation, AnnotationStatus, Sample, SampleStatus, Project
from schemas import AnnotationCreate, AnnotationSubmit
from services.consistency_service import check_annotation_consistency


def create_annotation(db: Session, annotator_id: int, annotation: AnnotationCreate) -> Annotation:
    db_annotation = Annotation(
        project_id=annotation.sample_id and db.query(Sample).filter(
            Sample.id == annotation.sample_id
        ).first().project_id if annotation.sample_id else 0,
        sample_id=annotation.sample_id,
        annotator_id=annotator_id,
        task_id=annotation.task_id,
        content=annotation.content,
        time_spent_seconds=annotation.time_spent_seconds,
        comment=annotation.comment,
    )

    sample = db.query(Sample).filter(Sample.id == annotation.sample_id).first()
    if sample:
        db_annotation.project_id = sample.project_id
        if sample.status == SampleStatus.ASSIGNED or sample.status == SampleStatus.PENDING:
            sample.status = SampleStatus.ANNOTATING

    db.add(db_annotation)
    db.commit()
    db.refresh(db_annotation)
    return db_annotation


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
) -> Optional[dict]:
    annotation = get_annotation(db, annotation_id)
    if not annotation:
        return None

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
    }


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

            result['action'] = 'conflict_created'
            result['conflict_created'] = True
        else:
            result['action'] = 'conflict_exists'
            result['conflict_created'] = False

    db.commit()
    return result


def delete_annotation(db: Session, annotation_id: int) -> bool:
    annotation = get_annotation(db, annotation_id)
    if not annotation:
        return False
    db.delete(annotation)
    db.commit()
    return True
