from typing import List, Optional
from sqlalchemy.orm import Session

from models import Sample, SampleStatus
from schemas import SampleCreate, SampleBatchCreate


def create_sample(db: Session, project_id: int, sample: SampleCreate) -> Sample:
    db_sample = Sample(
        project_id=project_id,
        external_id=sample.external_id,
        content=sample.content,
        content_url=sample.content_url,
        sample_metadata=sample.sample_metadata,
    )
    db.add(db_sample)
    db.commit()
    db.refresh(db_sample)
    return db_sample


def create_samples_batch(db: Session, project_id: int, samples: List[SampleCreate]) -> List[Sample]:
    db_samples = []
    for sample in samples:
        db_sample = Sample(
            project_id=project_id,
            external_id=sample.external_id,
            content=sample.content,
            content_url=sample.content_url,
            sample_metadata=sample.sample_metadata,
        )
        db_samples.append(db_sample)
        db.add(db_sample)
    db.commit()
    for s in db_samples:
        db.refresh(s)
    return db_samples


def get_sample(db: Session, sample_id: int) -> Optional[Sample]:
    return db.query(Sample).filter(Sample.id == sample_id).first()


def get_samples(
    db: Session,
    project_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    status: Optional[SampleStatus] = None,
) -> List[Sample]:
    query = db.query(Sample)
    if project_id:
        query = query.filter(Sample.project_id == project_id)
    if status:
        query = query.filter(Sample.status == status)
    return query.order_by(Sample.id.asc()).offset(skip).limit(limit).all()


def count_samples(
    db: Session,
    project_id: Optional[int] = None,
    status: Optional[SampleStatus] = None,
) -> int:
    query = db.query(Sample)
    if project_id:
        query = query.filter(Sample.project_id == project_id)
    if status:
        query = query.filter(Sample.status == status)
    return query.count()


def update_sample_status(db: Session, sample_id: int, status: SampleStatus) -> Optional[Sample]:
    sample = get_sample(db, sample_id)
    if not sample:
        return None
    sample.status = status
    db.commit()
    db.refresh(sample)
    return sample


def update_sample_annotation(
    db: Session,
    sample_id: int,
    final_annotation: dict,
    consistency_score: Optional[float] = None,
    consistency_level: Optional[str] = None,
) -> Optional[Sample]:
    sample = get_sample(db, sample_id)
    if not sample:
        return None

    sample.final_annotation = final_annotation
    sample.version += 1
    if consistency_score is not None:
        sample.consistency_score = consistency_score
    if consistency_level is not None:
        from models import ConsistencyLevel
        if isinstance(consistency_level, ConsistencyLevel):
            sample.consistency_level = consistency_level
        else:
            sample.consistency_level = ConsistencyLevel(consistency_level)

    db.commit()
    db.refresh(sample)
    return sample


def get_pending_samples_for_annotator(
    db: Session,
    project_id: int,
    annotator_id: int,
    required_annotators: int = 2,
    limit: int = 50,
) -> List[Sample]:
    from models import Annotation, TaskSample, Task

    annotated_subquery = (
        db.query(Annotation.sample_id)
        .filter(
            Annotation.annotator_id == annotator_id,
            Annotation.project_id == project_id,
        )
        .distinct()
        .subquery()
    )

    annotation_count_subquery = (
        db.query(
            Annotation.sample_id.label('sample_id'),
            db.func.count(Annotation.id).label('ann_count')
        )
        .filter(Annotation.project_id == project_id)
        .group_by(Annotation.sample_id)
        .subquery()
    )

    query = (
        db.query(Sample)
        .outerjoin(annotation_count_subquery, Sample.id == annotation_count_subquery.c.sample_id)
        .filter(
            Sample.project_id == project_id,
            Sample.id.notin_(annotated_subquery),
            Sample.status.in_([SampleStatus.PENDING, SampleStatus.ASSIGNED, SampleStatus.ANNOTATING]),
            db.or_(
                annotation_count_subquery.c.ann_count.is_(None),
                annotation_count_subquery.c.ann_count < required_annotators,
            )
        )
        .order_by(Sample.id.asc())
        .limit(limit)
    )

    return query.all()


def delete_sample(db: Session, sample_id: int) -> bool:
    sample = get_sample(db, sample_id)
    if not sample:
        return False
    db.delete(sample)
    db.commit()
    return True
