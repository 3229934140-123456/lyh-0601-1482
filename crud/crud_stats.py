from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import (
    User, Task, Sample, Annotation, QualityCheck,
    ReworkRecord, Project, TaskStatus, SampleStatus,
    AnnotationStatus, QualityStatus
)
from schemas import AnnotatorProgress, ProjectStats


def get_annotator_progress(
    db: Session,
    annotator_id: int,
    project_id: Optional[int] = None,
) -> List[AnnotatorProgress]:
    projects_query = db.query(Project)
    if project_id:
        projects_query = projects_query.filter(Project.id == project_id)
    projects = projects_query.all()

    results = []
    user = db.query(User).filter(User.id == annotator_id).first()
    if not user:
        return results

    for proj in projects:
        tasks = (
            db.query(Task)
            .filter(
                Task.assignee_id == annotator_id,
                Task.project_id == proj.id,
                Task.task_type == 'annotation',
            )
            .all()
        )

        total_assigned = len(tasks)
        completed = sum(1 for t in tasks if t.status in [
            TaskStatus.COMPLETED, TaskStatus.SUBMITTED,
        ])
        in_progress = sum(1 for t in tasks if t.status in [
            TaskStatus.IN_PROGRESS, TaskStatus.REVIEWING,
        ])

        annotations = (
            db.query(Annotation)
            .filter(
                Annotation.annotator_id == annotator_id,
                Annotation.project_id == proj.id,
            )
            .all()
        )

        rejected = sum(1 for a in annotations if a.status == AnnotationStatus.REJECTED)

        rework_count = (
            db.query(ReworkRecord)
            .filter(
                ReworkRecord.project_id == proj.id,
                ReworkRecord.rework_annotator_id == annotator_id,
            )
            .count()
        )

        qc_records = (
            db.query(QualityCheck)
            .filter(
                QualityCheck.project_id == proj.id,
                QualityCheck.checker_id == annotator_id,
                QualityCheck.quality_score.isnot(None),
            )
            .all()
        )
        quality_score_avg = None
        if qc_records:
            scores = [q.quality_score for q in qc_records if q.quality_score is not None]
            if scores:
                quality_score_avg = round(sum(scores) / len(scores), 4)

        time_records = [
            a.time_spent_seconds for a in annotations
            if a.time_spent_seconds is not None and a.time_spent_seconds > 0
        ]
        avg_time_per_sample = None
        if time_records:
            avg_time_per_sample = round(sum(time_records) / len(time_records), 2)

        all_annotations = (
            db.query(Annotation)
            .filter(Annotation.project_id == proj.id)
            .all()
        )
        from services.consistency_service import calculate_pairwise_consistency
        pairwise = calculate_pairwise_consistency(all_annotations)
        annotator_scores = []
        for p in pairwise:
            if p['annotator_1'] == annotator_id or p['annotator_2'] == annotator_id:
                annotator_scores.append(p['consistency_score'])
        consistency_rate = None
        if annotator_scores:
            consistency_rate = round(sum(annotator_scores) / len(annotator_scores), 4)

        last_annotation = (
            db.query(Annotation)
            .filter(
                Annotation.annotator_id == annotator_id,
                Annotation.project_id == proj.id,
            )
            .order_by(Annotation.updated_at.desc())
            .first()
        )
        last_active_at = last_annotation.updated_at if last_annotation else None

        progress = AnnotatorProgress(
            annotator_id=annotator_id,
            annotator_name=user.display_name,
            project_id=proj.id,
            project_name=proj.name,
            total_assigned=total_assigned,
            completed=completed,
            in_progress=in_progress,
            rejected=rejected,
            rework_count=rework_count,
            quality_score_avg=quality_score_avg,
            avg_time_per_sample=avg_time_per_sample,
            consistency_rate=consistency_rate,
            last_active_at=last_active_at,
        )
        results.append(progress)

    return results


def get_all_annotators_progress(
    db: Session,
    project_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[AnnotatorProgress]:
    from models import UserRole
    annotators = (
        db.query(User)
        .filter(User.role.in_([UserRole.ANNOTATOR, UserRole.QUALITY_CHECKER]))
        .order_by(User.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    results = []
    for annotator in annotators:
        progress_list = get_annotator_progress(db, annotator.id, project_id)
        results.extend(progress_list)
    return results


def get_project_stats(
    db: Session,
    project_id: int,
) -> Optional[ProjectStats]:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None

    total_samples = db.query(Sample).filter(Sample.project_id == project_id).count()

    status_counts = {}
    for status in SampleStatus:
        status_counts[status.value] = (
            db.query(Sample)
            .filter(Sample.project_id == project_id, Sample.status == status)
            .count()
        )

    total_tasks = db.query(Task).filter(
        Task.project_id == project_id,
        Task.task_type == 'annotation',
    ).count()

    active_tasks = db.query(Task).filter(
        Task.project_id == project_id,
        Task.task_type == 'annotation',
        Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.REVIEWING]),
    ).count()

    completed_tasks = db.query(Task).filter(
        Task.project_id == project_id,
        Task.task_type == 'annotation',
        Task.status.in_([TaskStatus.COMPLETED, TaskStatus.SUBMITTED]),
    ).count()

    annotator_ids = (
        db.query(Task.assignee_id)
        .filter(
            Task.project_id == project_id,
            Task.status != TaskStatus.COMPLETED,
        )
        .distinct()
        .all()
    )
    active_annotators = len([aid for (aid,) in annotator_ids if aid is not None])

    approved_samples = status_counts.get(SampleStatus.APPROVED.value, 0)
    conflict_samples = status_counts.get(SampleStatus.CONFLICT.value, 0)
    pending_samples = status_counts.get(SampleStatus.PENDING.value, 0)
    in_progress_samples = status_counts.get(SampleStatus.ANNOTATING.value, 0) + \
        status_counts.get(SampleStatus.ASSIGNED.value, 0)
    submitted_samples = status_counts.get(SampleStatus.SUBMITTED.value, 0)
    rejected_samples = status_counts.get(SampleStatus.REJECTED.value, 0)

    progress_percentage = 0.0
    if total_samples > 0:
        finished = approved_samples
        progress_percentage = round(finished / total_samples, 4)

    samples_with_consistency = (
        db.query(Sample.consistency_score)
        .filter(
            Sample.project_id == project_id,
            Sample.consistency_score.isnot(None),
        )
        .all()
    )
    avg_consistency_score = None
    if samples_with_consistency:
        scores = [s[0] for s in samples_with_consistency if s[0] is not None]
        if scores:
            avg_consistency_score = round(sum(scores) / len(scores), 4)

    qc_with_scores = (
        db.query(QualityCheck.quality_score)
        .filter(
            QualityCheck.project_id == project_id,
            QualityCheck.quality_score.isnot(None),
        )
        .all()
    )
    avg_quality_score = None
    if qc_with_scores:
        scores = [s[0] for s in qc_with_scores if s[0] is not None]
        if scores:
            avg_quality_score = round(sum(scores) / len(scores), 4)

    return ProjectStats(
        project_id=project_id,
        project_name=project.name,
        total_samples=total_samples,
        pending_samples=pending_samples,
        in_progress_samples=in_progress_samples,
        submitted_samples=submitted_samples,
        conflict_samples=conflict_samples,
        approved_samples=approved_samples,
        rejected_samples=rejected_samples,
        progress_percentage=progress_percentage,
        total_tasks=total_tasks,
        active_tasks=active_tasks,
        completed_tasks=completed_tasks,
        active_annotators=active_annotators,
        avg_consistency_score=avg_consistency_score,
        avg_quality_score=avg_quality_score,
    )


def get_all_projects_stats(
    db: Session,
    skip: int = 0,
    limit: int = 100,
) -> List[ProjectStats]:
    projects = (
        db.query(Project)
        .order_by(Project.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    results = []
    for proj in projects:
        stats = get_project_stats(db, proj.id)
        if stats:
            results.append(stats)
    return results
