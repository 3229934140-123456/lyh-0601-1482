from typing import List, Optional
from sqlalchemy.orm import Session

from models import Project, LabelSpec, User, Sample, Task, ProjectStatus
from schemas import ProjectCreate, ProjectUpdate, LabelSpecCreate


def create_project(db: Session, project: ProjectCreate) -> Project:
    db_project = Project(
        name=project.name,
        description=project.description,
        project_type=project.project_type,
        required_annotators=project.required_annotators,
        samples_per_task=project.samples_per_task,
        quality_sample_rate=project.quality_sample_rate,
        consistency_threshold=project.consistency_threshold,
        lock_timeout_seconds=project.lock_timeout_seconds,
        creator_id=project.creator_id,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    if project.label_specs:
        for spec in project.label_specs:
            db_spec = LabelSpec(
                project_id=db_project.id,
                name=spec.name,
                description=spec.description,
                value_type=spec.value_type,
                options=spec.options,
                required=spec.required,
                sort_order=spec.sort_order,
                parent_id=spec.parent_id,
            )
            db.add(db_spec)
        db.commit()
        db.refresh(db_project)

    return db_project


def get_project(db: Session, project_id: int) -> Optional[Project]:
    return db.query(Project).filter(Project.id == project_id).first()


def get_projects(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: Optional[ProjectStatus] = None,
    project_type: Optional[str] = None,
    creator_id: Optional[int] = None,
) -> List[Project]:
    query = db.query(Project)
    if status:
        query = query.filter(Project.status == status)
    if project_type:
        query = query.filter(Project.project_type == project_type)
    if creator_id:
        query = query.filter(Project.creator_id == creator_id)
    return query.order_by(Project.created_at.desc()).offset(skip).limit(limit).all()


def count_projects(
    db: Session,
    status: Optional[ProjectStatus] = None,
    project_type: Optional[str] = None,
    creator_id: Optional[int] = None,
) -> int:
    query = db.query(Project)
    if status:
        query = query.filter(Project.status == status)
    if project_type:
        query = query.filter(Project.project_type == project_type)
    if creator_id:
        query = query.filter(Project.creator_id == creator_id)
    return query.count()


def update_project(db: Session, project_id: int, project_update: ProjectUpdate) -> Optional[Project]:
    db_project = get_project(db, project_id)
    if not db_project:
        return None

    update_data = project_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_project, key, value)

    db.commit()
    db.refresh(db_project)
    return db_project


def delete_project(db: Session, project_id: int) -> bool:
    db_project = get_project(db, project_id)
    if not db_project:
        return False
    db.delete(db_project)
    db.commit()
    return True


def add_label_spec(db: Session, project_id: int, spec: LabelSpecCreate) -> Optional[LabelSpec]:
    project = get_project(db, project_id)
    if not project:
        return None

    db_spec = LabelSpec(
        project_id=project_id,
        name=spec.name,
        description=spec.description,
        value_type=spec.value_type,
        options=spec.options,
        required=spec.required,
        sort_order=spec.sort_order,
        parent_id=spec.parent_id,
    )
    db.add(db_spec)
    db.commit()
    db.refresh(db_spec)
    return db_spec


def get_label_specs(db: Session, project_id: int) -> List[LabelSpec]:
    return (
        db.query(LabelSpec)
        .filter(LabelSpec.project_id == project_id)
        .order_by(LabelSpec.sort_order.asc(), LabelSpec.id.asc())
        .all()
    )


def delete_label_spec(db: Session, spec_id: int) -> bool:
    spec = db.query(LabelSpec).filter(LabelSpec.id == spec_id).first()
    if not spec:
        return False
    db.delete(spec)
    db.commit()
    return True


def get_project_stats(db: Session, project_id: int) -> dict:
    project = get_project(db, project_id)
    if not project:
        return {}

    total_samples = db.query(Sample).filter(Sample.project_id == project_id).count()
    total_tasks = db.query(Task).filter(Task.project_id == project_id).count()

    from models import SampleStatus
    status_counts = {}
    for status in SampleStatus:
        count = db.query(Sample).filter(
            Sample.project_id == project_id,
            Sample.status == status
        ).count()
        status_counts[status.value] = count

    completed_statuses = [SampleStatus.APPROVED, SampleStatus.CONFLICT]
    completed_count = sum(status_counts.get(s.value, 0) for s in completed_statuses)

    return {
        'sample_count': total_samples,
        'task_count': total_tasks,
        'completed_sample_count': completed_count,
        'status_counts': status_counts,
    }
