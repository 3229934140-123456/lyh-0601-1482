from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import TaskStatus
from schemas import (
    TaskAssign, TaskClaim, LockTask, UnlockTask,
    Task, TaskDetail, TaskSample, AnnotationCreate,
    AnnotationSubmit, Annotation, ApiResponse, PaginatedResponse,
    ConsistencyCheckResult
)
from crud import crud_tasks, crud_annotations, crud_samples, crud_projects, crud_users

router = APIRouter(prefix="/tasks", tags=["任务流转"])


@router.post("/assign", response_model=ApiResponse, status_code=201)
def assign_task(
    task_assign: TaskAssign,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, task_assign.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    assignee = crud_users.get_user(db, task_assign.assignee_id)
    if not assignee:
        raise HTTPException(status_code=404, detail="标注员不存在")

    task = crud_tasks.assign_task(db, task_assign)
    if not task:
        return ApiResponse(
            code=400,
            message="没有可分配的样本，请等待更多样本或检查标注员状态",
            data=None,
        )

    return ApiResponse(data=task, message="任务分配成功")


@router.post("/claim", response_model=ApiResponse, status_code=201)
def claim_task(
    claim: TaskClaim,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, claim.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    annotator = crud_users.get_user(db, claim.annotator_id)
    if not annotator:
        raise HTTPException(status_code=404, detail="标注员不存在")

    task = crud_tasks.claim_task(
        db=db,
        project_id=claim.project_id,
        annotator_id=claim.annotator_id,
        sample_count=claim.sample_count,
    )
    if not task:
        return ApiResponse(
            code=400,
            message="暂无可领取的任务，请稍后再试",
            data=None,
        )

    return ApiResponse(data=task, message="任务领取成功")


@router.get("", response_model=ApiResponse)
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    task_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    total = crud_tasks.count_tasks(db, project_id, assignee_id, status_filter)
    tasks = crud_tasks.get_tasks(
        db, project_id, assignee_id, status_filter, task_type, skip, page_size
    )
    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=tasks,
    ))


@router.get("/{task_id}", response_model=ApiResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = crud_tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_samples = crud_tasks.get_task_samples(db, task_id)
    assignee = crud_users.get_user(db, task.assignee_id)

    samples_with_data = []
    for ts in task_samples:
        sample = crud_samples.get_sample(db, ts.sample_id)
        samples_with_data.append(TaskSample(
            id=ts.id,
            task_id=ts.task_id,
            sample_id=ts.sample_id,
            sort_order=ts.sort_order,
            is_completed=ts.is_completed,
            completed_at=ts.completed_at,
            sample=sample,
        ))

    task_detail = TaskDetail(
        **{c.name: getattr(task, c.name) for c in task.__table__.columns},
        assignee=assignee,
        samples=samples_with_data,
    )

    return ApiResponse(data=task_detail)


@router.post("/lock", response_model=ApiResponse)
def lock_task(lock: LockTask, db: Session = Depends(get_db)):
    task = crud_tasks.get_task(db, lock.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    project = crud_projects.get_project(db, task.project_id)
    timeout = project.lock_timeout_seconds if project else 1800

    locked = crud_tasks.lock_task(db, lock.task_id, lock.user_id, timeout)
    if not locked:
        return ApiResponse(
            code=409,
            message="任务已被其他用户锁定，请稍后再试",
            data=None,
        )

    return ApiResponse(data=locked, message="任务锁定成功")


@router.post("/unlock", response_model=ApiResponse)
def unlock_task(unlock: UnlockTask, db: Session = Depends(get_db)):
    task = crud_tasks.get_task(db, unlock.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    unlocked = crud_tasks.unlock_task(db, unlock.task_id, unlock.user_id)
    if not unlocked:
        return ApiResponse(
            code=400,
            message="任务未被该用户锁定，无法解锁",
            data=None,
        )

    return ApiResponse(data=unlocked, message="任务解锁成功")


@router.post("/{task_id}/annotations", response_model=ApiResponse, status_code=201)
def create_annotation(
    task_id: int,
    annotation: AnnotationCreate,
    annotator_id: int = Query(..., description="标注员ID"),
    db: Session = Depends(get_db),
):
    task = crud_tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.assignee_id != annotator_id:
        return ApiResponse(
            code=403,
            message="该任务不属于此标注员",
            data=None,
        )

    if task.status == TaskStatus.COMPLETED:
        return ApiResponse(
            code=400,
            message="任务已完成，无法添加标注",
            data=None,
        )

    if annotation.task_id is None:
        annotation.task_id = task_id

    db_annotation = crud_annotations.create_annotation(db, annotator_id, annotation)
    return ApiResponse(data=db_annotation, message="标注创建成功（草稿状态）")


@router.post("/annotations/{annotation_id}/submit", response_model=ApiResponse)
def submit_annotation(
    annotation_id: int,
    submission: AnnotationSubmit,
    db: Session = Depends(get_db),
):
    annotation = crud_annotations.get_annotation(db, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")

    if annotation.status not in ['draft', 'Draft']:
        from models import AnnotationStatus
        if annotation.status != AnnotationStatus.DRAFT:
            return ApiResponse(
                code=400,
                message=f"当前标注状态为 {annotation.status}，无法重复提交",
                data=None,
            )

    result = crud_annotations.submit_annotation(db, annotation_id, submission)
    if not result:
        raise HTTPException(status_code=500, detail="标注提交失败")

    return ApiResponse(
        data=result,
        message="标注提交成功",
    )


@router.get("/annotations/{annotation_id}", response_model=ApiResponse)
def get_annotation(annotation_id: int, db: Session = Depends(get_db)):
    annotation = crud_annotations.get_annotation(db, annotation_id)
    if not annotation:
        raise HTTPException(status_code=404, detail="标注不存在")

    annotator = crud_users.get_user(db, annotation.annotator_id)
    from schemas import AnnotationWithAnnotator
    data = AnnotationWithAnnotator(
        **{c.name: getattr(annotation, c.name) for c in annotation.__table__.columns},
        annotator=annotator,
    )

    return ApiResponse(data=data)


@router.post("/samples/{sample_id}/check-consistency", response_model=ApiResponse)
def check_sample_consistency(
    sample_id: int,
    db: Session = Depends(get_db),
):
    sample = crud_samples.get_sample(db, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="样本不存在")

    result = crud_annotations.process_sample_consistency(db, sample_id)

    annotations = crud_annotations.get_sample_annotations(db, sample_id)
    ann_with_users = []
    for ann in annotations:
        annotator = crud_users.get_user(db, ann.annotator_id)
        from schemas import AnnotationWithAnnotator
        ann_with_users.append(AnnotationWithAnnotator(
            **{c.name: getattr(ann, c.name) for c in ann.__table__.columns},
            annotator=annotator,
        ))

    from models import ConsistencyLevel
    level = result.get('consistency_level')
    if isinstance(level, str):
        try:
            level = ConsistencyLevel(level)
        except ValueError:
            level = ConsistencyLevel.LOW

    check_result = ConsistencyCheckResult(
        sample_id=sample_id,
        is_consistent=result.get('is_consistent', False),
        consistency_score=result.get('consistency_score', 0.0),
        consistency_level=level or ConsistencyLevel.LOW,
        conflict_fields=result.get('conflict_fields', []),
        majority_annotation=result.get('final_annotation'),
        annotations=ann_with_users,
    )

    return ApiResponse(data=check_result, message=result.get('message', '一致性检查完成'))


@router.post("/cleanup-locks", response_model=ApiResponse)
def cleanup_expired_locks(
    timeout_seconds: int = Query(1800, description="锁超时时间(秒)"),
    db: Session = Depends(get_db),
):
    count = crud_tasks.cleanup_expired_locks(db, timeout_seconds)
    return ApiResponse(
        data={"cleaned_count": count},
        message=f"已清理 {count} 个过期任务锁",
    )
