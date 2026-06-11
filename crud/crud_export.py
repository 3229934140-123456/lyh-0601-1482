from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from models import (
    ExportJob, Sample, Annotation, Project, SampleStatus,
    LabelSpec
)
from schemas import ExportJobCreate, ResultSummary
from services.export_service import (
    export_to_json, export_to_csv, save_export_file
)


def create_export_job(db: Session, job: ExportJobCreate) -> ExportJob:
    db_job = ExportJob(
        project_id=job.project_id,
        creator_id=job.creator_id,
        export_format=job.export_format,
        include_metadata=job.include_metadata,
        filters=job.filters,
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job


def get_export_job(db: Session, job_id: int) -> Optional[ExportJob]:
    return db.query(ExportJob).filter(ExportJob.id == job_id).first()


def get_export_jobs(
    db: Session,
    project_id: Optional[int] = None,
    creator_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[ExportJob]:
    query = db.query(ExportJob)
    if project_id:
        query = query.filter(ExportJob.project_id == project_id)
    if creator_id:
        query = query.filter(ExportJob.creator_id == creator_id)
    if status:
        query = query.filter(ExportJob.status == status)
    return query.order_by(ExportJob.created_at.desc()).offset(skip).limit(limit).all()


def _apply_sample_filters(
    query,
    filters: Optional[Dict[str, Any]],
):
    if not filters:
        return query

    status_filter = filters.get('status')
    if status_filter:
        if isinstance(status_filter, list):
            statuses = [SampleStatus(s) if isinstance(s, str) else s for s in status_filter]
            query = query.filter(Sample.status.in_(statuses))
        elif isinstance(status_filter, str):
            query = query.filter(Sample.status == SampleStatus(status_filter))

    min_consistency = filters.get('min_consistency')
    if min_consistency is not None:
        query = query.filter(
            Sample.consistency_score.isnot(None),
            Sample.consistency_score >= float(min_consistency),
        )

    sample_ids = filters.get('sample_ids')
    if sample_ids and isinstance(sample_ids, list):
        query = query.filter(Sample.id.in_(sample_ids))

    return query


def execute_export_job(db: Session, job_id: int) -> Optional[ExportJob]:
    job = get_export_job(db, job_id)
    if not job:
        return None

    try:
        job.status = 'processing'
        db.commit()

        project = db.query(Project).filter(Project.id == job.project_id).first()
        if not project:
            raise ValueError(f"Project {job.project_id} not found")

        samples_query = db.query(Sample).filter(Sample.project_id == job.project_id)
        samples_query = _apply_sample_filters(samples_query, job.filters)
        samples = samples_query.order_by(Sample.id.asc()).all()

        sample_ids = [s.id for s in samples]

        annotations = []
        if sample_ids:
            annotations = (
                db.query(Annotation)
                .filter(Annotation.sample_id.in_(sample_ids))
                .order_by(Annotation.sample_id.asc(), Annotation.created_at.asc())
                .all()
            )

        label_specs = (
            db.query(LabelSpec)
            .filter(LabelSpec.project_id == job.project_id)
            .order_by(LabelSpec.sort_order.asc())
            .all()
        )

        fmt = job.export_format.lower()
        if fmt in ('json',):
            content = export_to_json(
                samples=samples,
                annotations=annotations,
                project=project,
                include_metadata=job.include_metadata,
                label_specs=label_specs,
            )
        elif fmt in ('csv',):
            content = export_to_csv(
                samples=samples,
                annotations=annotations,
                project=project,
                include_metadata=job.include_metadata,
                label_specs=label_specs,
            )
        else:
            content = export_to_json(
                samples=samples,
                annotations=annotations,
                project=project,
                include_metadata=job.include_metadata,
                label_specs=label_specs,
            )

        filepath = save_export_file(content, fmt, job.project_id)

        job.file_path = filepath
        job.status = 'completed'
        job.completed_at = datetime.utcnow()

        db.commit()
        db.refresh(job)
        return job

    except Exception as e:
        job.status = 'failed'
        job.error_message = str(e)
        db.commit()
        db.refresh(job)
        return job


def get_result_summary(db: Session, project_id: int) -> Optional[ResultSummary]:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None

    total_samples = db.query(Sample).filter(Sample.project_id == project_id).count()
    approved_samples = (
        db.query(Sample)
        .filter(
            Sample.project_id == project_id,
            Sample.status == SampleStatus.APPROVED,
        )
        .count()
    )

    approval_rate = round(approved_samples / total_samples, 4) if total_samples > 0 else 0.0

    total_annotations = db.query(Annotation).filter(Annotation.project_id == project_id).count()

    avg_consistency_score = None
    consistency_scores = (
        db.query(Sample.consistency_score)
        .filter(
            Sample.project_id == project_id,
            Sample.consistency_score.isnot(None),
        )
        .all()
    )
    if consistency_scores:
        scores = [s[0] for s in consistency_scores if s[0] is not None]
        if scores:
            avg_consistency_score = round(sum(scores) / len(scores), 4)

    from models import QualityCheck
    avg_quality_score = None
    qc_scores = (
        db.query(QualityCheck.quality_score)
        .filter(
            QualityCheck.project_id == project_id,
            QualityCheck.quality_score.isnot(None),
        )
        .all()
    )
    if qc_scores:
        scores = [s[0] for s in qc_scores if s[0] is not None]
        if scores:
            avg_quality_score = round(sum(scores) / len(scores), 4)

    label_distribution: Dict[str, Dict[str, int]] = {}
    approved_sample_list = (
        db.query(Sample)
        .filter(
            Sample.project_id == project_id,
            Sample.status == SampleStatus.APPROVED,
            Sample.final_annotation.isnot(None),
        )
        .all()
    )

    for sample in approved_sample_list:
        fa = sample.final_annotation or {}
        for label_name, label_value in fa.items():
            if label_name not in label_distribution:
                label_distribution[label_name] = {}

            if isinstance(label_value, list):
                for v in label_value:
                    v_str = str(v)
                    label_distribution[label_name][v_str] = label_distribution[label_name].get(v_str, 0) + 1
            elif isinstance(label_value, dict):
                continue
            else:
                v_str = str(label_value)
                label_distribution[label_name][v_str] = label_distribution[label_name].get(v_str, 0) + 1

    top_labels = []
    for label_name, values in label_distribution.items():
        sorted_values = sorted(values.items(), key=lambda x: -x[1])
        for value, count in sorted_values[:3]:
            top_labels.append({
                'label_name': label_name,
                'label_value': value,
                'count': count,
                'percentage': round(count / max(approved_samples, 1), 4),
            })
    top_labels = sorted(top_labels, key=lambda x: -x['count'])[:10]

    from models import User, AnnotationStatus
    annotator_rankings = []
    annotator_ids = (
        db.query(Annotation.annotator_id)
        .filter(Annotation.project_id == project_id)
        .distinct()
        .all()
    )

    for (aid,) in annotator_ids:
        if aid is None:
            continue
        user = db.query(User).filter(User.id == aid).first()
        if not user:
            continue

        ann_count = (
            db.query(Annotation)
            .filter(
                Annotation.project_id == project_id,
                Annotation.annotator_id == aid,
                Annotation.status == AnnotationStatus.APPROVED,
            )
            .count()
        )

        total_ann_count = (
            db.query(Annotation)
            .filter(
                Annotation.project_id == project_id,
                Annotation.annotator_id == aid,
            )
            .count()
        )

        acc_rate = round(ann_count / max(total_ann_count, 1), 4)

        annotator_rankings.append({
            'annotator_id': aid,
            'annotator_name': user.display_name,
            'approved_count': ann_count,
            'total_count': total_ann_count,
            'accuracy_rate': acc_rate,
        })

    annotator_rankings = sorted(annotator_rankings, key=lambda x: (-x['approved_count'], -x['accuracy_rate']))

    return ResultSummary(
        project_id=project_id,
        project_name=project.name,
        project_type=project.project_type.value if hasattr(project.project_type, 'value') else str(project.project_type),
        total_samples=total_samples,
        approved_samples=approved_samples,
        approval_rate=approval_rate,
        total_annotations=total_annotations,
        avg_consistency_score=avg_consistency_score,
        avg_quality_score=avg_quality_score,
        label_distribution=label_distribution,
        top_labels=top_labels,
        annotator_rankings=annotator_rankings,
    )
