from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session

from models import Task, TaskSample, Sample, TaskStatus, SampleStatus, User, Project
from schemas import TaskCreate, TaskAssign


def create_task(db: Session, task: TaskCreate, sample_ids: Optional[List[int]] = None) -> Task:
    db_task = Task(
        project_id=task.project_id,
        assignee_id=task.assignee_id,
        task_type=task.task_type,
        note=task.note,
        deadline=task.deadline,
    )
    db.add(db_task)
    db.flush()

    if sample_ids:
        for idx, sample_id in enumerate(sample_ids):
            ts = TaskSample(
                task_id=db_task.id,
                sample_id=sample_id,
                sort_order=idx,
            )
            db.add(ts)
            sample = db.query(Sample).filter(Sample.id == sample_id).first()
            if sample and sample.status == SampleStatus.PENDING:
                sample.status = SampleStatus.ASSIGNED

    db.commit()
    db.refresh(db_task)
    return db_task


def assign_task(db: Session, task_assign: TaskAssign) -> Optional[Task]:
    from crud.crud_samples import get_pending_samples_for_annotator

    project = db.query(Project).filter(Project.id == task_assign.project_id).first()
    if not project:
        return None

    required_annotators = project.required_annotators
    samples_per_task = min(task_assign.sample_count, project.samples_per_task)

    samples = get_pending_samples_for_annotator(
        db=db,
        project_id=task_assign.project_id,
        annotator_id=task_assign.assignee_id,
        required_annotators=required_annotators,
        limit=samples_per_task,
    )

    if not samples:
        return None

    sample_ids = [s.id for s in samples]

    task = TaskCreate(
        project_id=task_assign.project_id,
        assignee_id=task_assign.assignee_id,
        task_type=task_assign.task_type,
    )

    return create_task(db, task, sample_ids)


def claim_task(
    db: Session,
    project_id: int,
    annotator_id: int,
    sample_count: Optional[int] = None,
) -> Optional[Task]:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return None

    count = sample_count or project.samples_per_task
    task_assign = TaskAssign(
        project_id=project_id,
        assignee_id=annotator_id,
        sample_count=count,
    )
    return assign_task(db, task_assign)


def get_task(db: Session, task_id: int) -> Optional[Task]:
    return db.query(Task).filter(Task.id == task_id).first()


def get_tasks(
    db: Session,
    project_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
    task_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> List[Task]:
    query = db.query(Task)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if status:
        query = query.filter(Task.status == status)
    if task_type:
        query = query.filter(Task.task_type == task_type)
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def count_tasks(
    db: Session,
    project_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status: Optional[TaskStatus] = None,
) -> int:
    query = db.query(Task)
    if project_id:
        query = query.filter(Task.project_id == project_id)
    if assignee_id:
        query = query.filter(Task.assignee_id == assignee_id)
    if status:
        query = query.filter(Task.status == status)
    return query.count()


def lock_task(db: Session, task_id: int, user_id: int, timeout_seconds: int = 1800) -> Optional[Task]:
    task = get_task(db, task_id)
    if not task:
        return None

    now = datetime.utcnow()
    if task.locked_by is not None and task.locked_at is not None:
        if task.locked_by != user_id:
            if (now - task.locked_at) <= timedelta(seconds=timeout_seconds):
                return None

    task.locked_by = user_id
    task.locked_at = now
    if task.status == TaskStatus.PENDING:
        task.status = TaskStatus.IN_PROGRESS

    db.commit()
    db.refresh(task)
    return task


def unlock_task(db: Session, task_id: int, user_id: int) -> Optional[Task]:
    task = get_task(db, task_id)
    if not task:
        return None

    if task.locked_by is None or task.locked_by != user_id:
        return None

    task.locked_by = None
    task.locked_at = None

    db.commit()
    db.refresh(task)
    return task


def update_task_progress(db: Session, task_id: int) -> Optional[Task]:
    task = get_task(db, task_id)
    if not task:
        return None

    task_samples = db.query(TaskSample).filter(TaskSample.task_id == task_id).all()
    if not task_samples:
        task.progress = 0.0
    else:
        completed = sum(1 for ts in task_samples if ts.is_completed)
        task.progress = round(completed / len(task_samples), 4)

    if task.progress >= 1.0 and task.status == TaskStatus.IN_PROGRESS:
        task.status = TaskStatus.SUBMITTED

    db.commit()
    db.refresh(task)
    return task


def mark_task_sample_completed(
    db: Session, task_id: int, sample_id: int
) -> Optional[TaskSample]:
    ts = (
        db.query(TaskSample)
        .filter(TaskSample.task_id == task_id, TaskSample.sample_id == sample_id)
        .first()
    )
    if not ts:
        return None

    ts.is_completed = True
    ts.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(ts)

    update_task_progress(db, task_id)
    return ts


def get_task_samples(db: Session, task_id: int) -> List[TaskSample]:
    return (
        db.query(TaskSample)
        .filter(TaskSample.task_id == task_id)
        .order_by(TaskSample.sort_order.asc())
        .all()
    )


def update_task_status(db: Session, task_id: int, status: TaskStatus) -> Optional[Task]:
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = status
    db.commit()
    db.refresh(task)
    return task


def cleanup_expired_locks(db: Session, timeout_seconds: int = 1800) -> int:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=timeout_seconds)

    expired = (
        db.query(Task)
        .filter(
            Task.locked_by.isnot(None),
            Task.locked_at < cutoff,
        )
        .all()
    )

    count = 0
    for task in expired:
        task.locked_by = None
        task.locked_at = None
        count += 1

    if count > 0:
        db.commit()

    return count
