from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import QualityStatus, TaskStatus
from schemas import (
    QualityCheckCreate, QualityCheckSubmit, QualityCheck,
    QualitySampleRequest, ConflictRecord, ConflictResolve,
    ReviewTaskSubmit, ReviewTask, ReworkRecordCreate, ReworkRecord,
    ApiResponse, PaginatedResponse, UserLite
)
from crud import crud_quality, crud_projects, crud_users

router = APIRouter(prefix="/quality", tags=["质量复核"])


@router.post("/sample", response_model=ApiResponse, status_code=201)
def create_quality_checks_by_sampling(
    req: QualitySampleRequest,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    checker = crud_users.get_user(db, req.checker_id)
    if not checker:
        raise HTTPException(status_code=404, detail="质检员不存在")

    qcs = crud_quality.create_quality_check_batch(
        db=db,
        project_id=req.project_id,
        checker_id=req.checker_id,
        sample_count=req.sample_count,
        sample_rate=req.sample_rate,
    )

    return ApiResponse(
        data={"count": len(qcs), "quality_checks": qcs},
        message=f"抽样创建了 {len(qcs)} 个质检任务",
    )


@router.post("/checks", response_model=ApiResponse, status_code=201)
def create_quality_check(
    qc: QualityCheckCreate,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, qc.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    checker = crud_users.get_user(db, qc.checker_id)
    if not checker:
        raise HTTPException(status_code=404, detail="质检员不存在")

    db_qc = crud_quality.create_quality_check(db, qc)
    return ApiResponse(data=db_qc, message="质检任务创建成功")


@router.get("/checks", response_model=ApiResponse)
def list_quality_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    checker_id: Optional[int] = None,
    status_filter: Optional[QualityStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    total = db.query(crud_quality.QualityCheck)
    if project_id:
        total = total.filter(crud_quality.QualityCheck.project_id == project_id)
    if sample_id:
        total = total.filter(crud_quality.QualityCheck.sample_id == sample_id)
    if checker_id:
        total = total.filter(crud_quality.QualityCheck.checker_id == checker_id)
    if status_filter:
        total = total.filter(crud_quality.QualityCheck.status == status_filter)
    total_count = total.count()

    qcs = crud_quality.get_quality_checks(
        db, project_id, sample_id, checker_id, status_filter, skip, page_size
    )

    qcs_with_checker = []
    for qc in qcs:
        checker = crud_users.get_user(db, qc.checker_id)
        qc_dict = {c.name: getattr(qc, c.name) for c in qc.__table__.columns}
        qc_dict['checker'] = UserLite(
            id=checker.id, username=checker.username,
            display_name=checker.display_name, role=checker.role,
        ) if checker else None
        qcs_with_checker.append(qc_dict)

    total_pages = (total_count + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total_count, page=page, page_size=page_size,
        total_pages=total_pages, items=qcs_with_checker,
    ))


@router.get("/checks/{qc_id}", response_model=ApiResponse)
def get_quality_check(qc_id: int, db: Session = Depends(get_db)):
    qc = crud_quality.get_quality_check(db, qc_id)
    if not qc:
        raise HTTPException(status_code=404, detail="质检记录不存在")

    checker = crud_users.get_user(db, qc.checker_id)
    qc_dict = {c.name: getattr(qc, c.name) for c in qc.__table__.columns}
    qc_dict['checker'] = checker

    return ApiResponse(data=qc_dict)


@router.post("/checks/{qc_id}/submit", response_model=ApiResponse)
def submit_quality_check(
    qc_id: int,
    submission: QualityCheckSubmit,
    db: Session = Depends(get_db),
):
    qc = crud_quality.get_quality_check(db, qc_id)
    if not qc:
        raise HTTPException(status_code=404, detail="质检记录不存在")

    if qc.status != QualityStatus.PENDING:
        return ApiResponse(
            code=400,
            message=f"质检记录状态为 {qc.status}，无法重复提交",
            data=None,
        )

    result = crud_quality.submit_quality_check(db, qc_id, submission)
    if not result:
        raise HTTPException(status_code=500, detail="质检提交失败")

    return ApiResponse(data=result, message="质检结果提交成功")


@router.get("/conflicts", response_model=ApiResponse)
def list_conflicts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    sample_id: Optional[int] = None,
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    total = crud_quality.count_conflicts(db, project_id, resolved)
    conflicts = crud_quality.get_conflicts(
        db, project_id, sample_id, resolved, skip, page_size
    )

    conflicts_with_sample = []
    for conflict in conflicts:
        from crud import crud_samples
        sample = crud_samples.get_sample(db, conflict.sample_id)
        conflict_dict = {c.name: getattr(conflict, c.name) for c in conflict.__table__.columns}
        conflict_dict['sample'] = sample
        conflicts_with_sample.append(conflict_dict)

    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=conflicts_with_sample,
    ))


@router.get("/conflicts/{conflict_id}", response_model=ApiResponse)
def get_conflict(conflict_id: int, db: Session = Depends(get_db)):
    conflict = crud_quality.get_conflict(db, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="冲突记录不存在")

    from crud import crud_samples, crud_annotations
    sample = crud_samples.get_sample(db, conflict.sample_id)
    annotations = crud_annotations.get_sample_annotations(db, conflict.sample_id)

    conflict_dict = {c.name: getattr(conflict, c.name) for c in conflict.__table__.columns}
    conflict_dict['sample'] = sample
    conflict_dict['annotations'] = annotations

    return ApiResponse(data=conflict_dict)


@router.post("/conflicts/{conflict_id}/resolve", response_model=ApiResponse)
def resolve_conflict(
    conflict_id: int,
    resolution: ConflictResolve,
    db: Session = Depends(get_db),
):
    conflict = crud_quality.get_conflict(db, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="冲突记录不存在")

    if conflict.resolved:
        return ApiResponse(
            code=400,
            message="该冲突已解决，无法重复操作",
            data=None,
        )

    resolver = crud_users.get_user(db, resolution.resolver_id)
    if not resolver:
        raise HTTPException(status_code=404, detail="处理人不存在")

    result = crud_quality.resolve_conflict(db, conflict_id, resolution)
    if not result:
        raise HTTPException(status_code=500, detail="冲突解决失败")

    return ApiResponse(data=result, message="冲突解决成功")


@router.post("/conflicts/{conflict_id}/review-tasks", response_model=ApiResponse, status_code=201)
def create_review_task(
    conflict_id: int,
    assignee_id: int,
    db: Session = Depends(get_db),
):
    conflict = crud_quality.get_conflict(db, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="冲突记录不存在")

    assignee = crud_users.get_user(db, assignee_id)
    if not assignee:
        raise HTTPException(status_code=404, detail="复核人不存在")

    rt = crud_quality.create_review_task(db, conflict_id, assignee_id)
    if not rt:
        raise HTTPException(status_code=500, detail="复核任务创建失败")

    return ApiResponse(data=rt, message="复核任务创建成功")


@router.get("/review-tasks", response_model=ApiResponse)
def list_review_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    rts = crud_quality.get_review_tasks(
        db, project_id, assignee_id, status_filter, skip, page_size
    )
    total = len(rts) if skip == 0 else 9999

    rts_with_data = []
    for rt in rts:
        assignee = crud_users.get_user(db, rt.assignee_id)
        rt_dict = {c.name: getattr(rt, c.name) for c in rt.__table__.columns}
        rt_dict['assignee'] = assignee
        rts_with_data.append(rt_dict)

    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=rts_with_data,
    ))


@router.post("/review-tasks/{rt_id}/submit", response_model=ApiResponse)
def submit_review_task(
    rt_id: int,
    submission: ReviewTaskSubmit,
    db: Session = Depends(get_db),
):
    rt = crud_quality.get_review_task(db, rt_id)
    if not rt:
        raise HTTPException(status_code=404, detail="复核任务不存在")

    if rt.status != TaskStatus.PENDING and rt.status != TaskStatus.IN_PROGRESS:
        return ApiResponse(
            code=400,
            message=f"复核任务状态为 {rt.status}，无法重复提交",
            data=None,
        )

    checker = crud_users.get_user(db, submission.checker_id)
    if not checker:
        raise HTTPException(status_code=404, detail="复核人不存在")

    result = crud_quality.submit_review_task(db, rt_id, submission)
    if not result:
        raise HTTPException(status_code=500, detail="复核提交失败")

    return ApiResponse(data=result, message="复核结果提交成功")


@router.post("/reworks", response_model=ApiResponse, status_code=201)
def create_rework(
    rework: ReworkRecordCreate,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, rework.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    original_annotator = crud_users.get_user(db, rework.original_annotator_id)
    if not original_annotator:
        raise HTTPException(status_code=404, detail="原标注员不存在")

    db_rework = crud_quality.create_rework(db, rework)
    return ApiResponse(data=db_rework, message="返工任务创建成功")


@router.get("/reworks", response_model=ApiResponse)
def list_reworks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    original_annotator_id: Optional[int] = None,
    rework_annotator_id: Optional[int] = None,
    status_filter: Optional[TaskStatus] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    reworks = crud_quality.get_reworks(
        db, project_id, None, original_annotator_id,
        rework_annotator_id, status_filter, skip, page_size
    )
    total = len(reworks) if skip == 0 else 9999

    from crud import crud_samples
    reworks_with_sample = []
    for rw in reworks:
        sample = crud_samples.get_sample(db, rw.sample_id)
        rw_dict = {c.name: getattr(rw, c.name) for c in rw.__table__.columns}
        rw_dict['sample'] = sample
        reworks_with_sample.append(rw_dict)

    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=reworks_with_sample,
    ))


@router.post("/reworks/{rework_id}/complete", response_model=ApiResponse)
def complete_rework(
    rework_id: int,
    new_annotation_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    rework = crud_quality.get_rework(db, rework_id)
    if not rework:
        raise HTTPException(status_code=404, detail="返工记录不存在")

    if rework.status == TaskStatus.COMPLETED:
        return ApiResponse(
            code=400,
            message="返工任务已完成，无法重复操作",
            data=None,
        )

    completed = crud_quality.complete_rework(db, rework_id, new_annotation_id)
    return ApiResponse(data=completed, message="返工任务完成")
