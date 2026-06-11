from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import UserRole
from schemas import (
    AnnotatorProgress, ProjectStats, User, UserCreate,
    ApiResponse, PaginatedResponse
)
from crud import crud_stats, crud_users, crud_projects

router = APIRouter(prefix="/stats", tags=["人员统计"])


@router.get("/annotators/{annotator_id}/progress", response_model=ApiResponse)
def get_annotator_progress(
    annotator_id: int,
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    annotator = crud_users.get_user(db, annotator_id)
    if not annotator:
        raise HTTPException(status_code=404, detail="标注员不存在")

    progress = crud_stats.get_annotator_progress(db, annotator_id, project_id)
    return ApiResponse(data=progress)


@router.get("/annotators/progress", response_model=ApiResponse)
def list_annotators_progress(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    progress_list = crud_stats.get_all_annotators_progress(db, project_id, skip, page_size)

    from models import UserRole as UR
    total_annotators = crud_users.count_users(
        db, role=UR.ANNOTATOR, is_active=True
    )
    total_qc = crud_users.count_users(
        db, role=UR.QUALITY_CHECKER, is_active=True
    )
    total = total_annotators + total_qc

    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=progress_list,
    ))


@router.get("/projects/{project_id}", response_model=ApiResponse)
def get_project_stats(
    project_id: int,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    stats = crud_stats.get_project_stats(db, project_id)
    if not stats:
        raise HTTPException(status_code=500, detail="项目统计数据获取失败")

    return ApiResponse(data=stats)


@router.get("/projects", response_model=ApiResponse)
def list_projects_stats(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    stats_list = crud_stats.get_all_projects_stats(db, skip, page_size)

    total = crud_projects.count_projects(db)
    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=stats_list,
    ))


@router.get("/users", response_model=ApiResponse)
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    total = crud_users.count_users(db, role, is_active)
    users = crud_users.get_users(db, role, is_active, skip, page_size)
    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=users,
    ))


@router.post("/users", response_model=ApiResponse, status_code=201)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
):
    existing = crud_users.get_user_by_username(db, user.username)
    if existing:
        return ApiResponse(
            code=409,
            message="用户名已存在",
            data=None,
        )

    db_user = crud_users.create_user(db, user)
    return ApiResponse(data=db_user, message="用户创建成功")


@router.get("/users/{user_id}", response_model=ApiResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = crud_users.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ApiResponse(data=user)


@router.put("/users/{user_id}/role", response_model=ApiResponse)
def update_user_role(
    user_id: int,
    role: UserRole,
    db: Session = Depends(get_db),
):
    user = crud_users.update_user_role(db, user_id, role)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ApiResponse(data=user, message="用户角色更新成功")


@router.post("/users/{user_id}/toggle-active", response_model=ApiResponse)
def toggle_user_active(user_id: int, db: Session = Depends(get_db)):
    user = crud_users.toggle_user_active(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return ApiResponse(data=user, message="用户状态更新成功")


@router.get("/overview", response_model=ApiResponse)
def get_overview_stats(db: Session = Depends(get_db)):
    from models import (
        Project, Sample, Task, Annotation,
        ProjectStatus, SampleStatus, TaskStatus
    )

    total_projects = crud_projects.count_projects(db)
    active_projects = crud_projects.count_projects(db, status=ProjectStatus.IN_PROGRESS)
    completed_projects = crud_projects.count_projects(db, status=ProjectStatus.COMPLETED)

    from crud import crud_samples, crud_tasks, crud_annotations

    total_samples = crud_samples.count_samples(db)
    approved_samples = crud_samples.count_samples(db, status=SampleStatus.APPROVED)
    pending_samples = crud_samples.count_samples(db, status=SampleStatus.PENDING)
    conflict_samples = crud_samples.count_samples(db, status=SampleStatus.CONFLICT)

    total_tasks = crud_tasks.count_tasks(db)
    active_tasks = crud_tasks.count_tasks(db, status=TaskStatus.IN_PROGRESS)
    completed_tasks = crud_tasks.count_tasks(db, status=TaskStatus.COMPLETED)

    total_annotations = crud_annotations.count_annotations(db)

    from models import UserRole as UR
    total_annotators = crud_users.count_users(db, role=UR.ANNOTATOR, is_active=True)
    total_qc = crud_users.count_users(db, role=UR.QUALITY_CHECKER, is_active=True)

    from crud import crud_quality
    total_conflicts = crud_quality.count_conflicts(db)
    unresolved_conflicts = crud_quality.count_conflicts(db, resolved=False)

    overview = {
        'projects': {
            'total': total_projects,
            'active': active_projects,
            'completed': completed_projects,
            'other': total_projects - active_projects - completed_projects,
        },
        'samples': {
            'total': total_samples,
            'approved': approved_samples,
            'pending': pending_samples,
            'conflict': conflict_samples,
            'approval_rate': round(approved_samples / max(total_samples, 1), 4),
        },
        'tasks': {
            'total': total_tasks,
            'active': active_tasks,
            'completed': completed_tasks,
        },
        'annotations': {
            'total': total_annotations,
        },
        'users': {
            'total_annotators': total_annotators,
            'total_quality_checkers': total_qc,
        },
        'conflicts': {
            'total': total_conflicts,
            'unresolved': unresolved_conflicts,
        },
    }

    return ApiResponse(data=overview, message="总览数据获取成功")
