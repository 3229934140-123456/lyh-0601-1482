from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import ProjectStatus, ProjectType, UserRole
from schemas import (
    ProjectCreate, ProjectUpdate, Project, ProjectDetail,
    LabelSpecCreate, LabelSpec, SampleCreate, SampleBatchCreate,
    Sample, ApiResponse, PaginatedResponse
)
from crud import crud_projects, crud_samples, crud_users

router = APIRouter(prefix="/projects", tags=["项目管理"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
):
    creator = crud_users.get_user(db, project.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="创建者用户不存在")

    db_project = crud_projects.create_project(db, project)
    stats = crud_projects.get_project_stats(db, db_project.id)

    project_detail = ProjectDetail(
        **{c.name: getattr(db_project, c.name) for c in db_project.__table__.columns},
        creator=creator,
        label_specs=db_project.label_specs or [],
        sample_count=stats.get('sample_count', 0),
        task_count=stats.get('task_count', 0),
        completed_sample_count=stats.get('completed_sample_count', 0),
    )

    return ApiResponse(data=project_detail, message="项目创建成功")


@router.get("", response_model=ApiResponse)
def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[ProjectStatus] = Query(None, alias="status"),
    project_type: Optional[ProjectType] = None,
    creator_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    total = crud_projects.count_projects(db, status_filter, project_type, creator_id)
    projects = crud_projects.get_projects(
        db, skip, page_size, status_filter, project_type, creator_id
    )
    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=projects,
    ))


@router.get("/{project_id}", response_model=ApiResponse)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    stats = crud_projects.get_project_stats(db, project_id)
    creator = crud_users.get_user(db, project.creator_id)
    label_specs = crud_projects.get_label_specs(db, project_id)

    project_detail = ProjectDetail(
        **{c.name: getattr(project, c.name) for c in project.__table__.columns},
        creator=creator,
        label_specs=label_specs,
        sample_count=stats.get('sample_count', 0),
        task_count=stats.get('task_count', 0),
        completed_sample_count=stats.get('completed_sample_count', 0),
    )

    return ApiResponse(data=project_detail)


@router.put("/{project_id}", response_model=ApiResponse)
def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: Session = Depends(get_db),
):
    updated = crud_projects.update_project(db, project_id, project_update)
    if not updated:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ApiResponse(data=updated, message="项目更新成功")


@router.delete("/{project_id}", response_model=ApiResponse)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    success = crud_projects.delete_project(db, project_id)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ApiResponse(message="项目删除成功")


@router.post("/{project_id}/label-specs", response_model=ApiResponse, status_code=201)
def add_label_spec(
    project_id: int,
    spec: LabelSpecCreate,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    db_spec = crud_projects.add_label_spec(db, project_id, spec)
    return ApiResponse(data=db_spec, message="标签规范添加成功")


@router.get("/{project_id}/label-specs", response_model=ApiResponse)
def list_label_specs(project_id: int, db: Session = Depends(get_db)):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    specs = crud_projects.get_label_specs(db, project_id)
    return ApiResponse(data=specs)


@router.delete("/{project_id}/label-specs/{spec_id}", response_model=ApiResponse)
def delete_label_spec(
    project_id: int,
    spec_id: int,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    success = crud_projects.delete_label_spec(db, spec_id)
    if not success:
        raise HTTPException(status_code=404, detail="标签规范不存在")
    return ApiResponse(message="标签规范删除成功")


@router.post("/{project_id}/samples", response_model=ApiResponse, status_code=201)
def add_sample(
    project_id: int,
    sample: SampleCreate,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    db_sample = crud_samples.create_sample(db, project_id, sample)
    return ApiResponse(data=db_sample, message="样本添加成功")


@router.post("/{project_id}/samples/batch", response_model=ApiResponse, status_code=201)
def add_samples_batch(
    project_id: int,
    batch: SampleBatchCreate,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    samples = crud_samples.create_samples_batch(db, project_id, batch.samples)
    return ApiResponse(
        data={"count": len(samples), "samples": samples},
        message=f"批量添加{len(samples)}个样本成功",
    )


@router.get("/{project_id}/samples", response_model=ApiResponse)
def list_samples(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    skip = (page - 1) * page_size
    status_enum = None
    if status_filter:
        from models import SampleStatus
        try:
            status_enum = SampleStatus(status_filter)
        except ValueError:
            pass

    total = crud_samples.count_samples(db, project_id, status_enum)
    samples = crud_samples.get_samples(db, project_id, skip, page_size, status_enum)
    total_pages = (total + page_size - 1) // page_size

    def _sample_to_dict(s):
        if s is None: return None
        d = {}
        for c in s.__table__.columns:
            col = c.name
            if col == 'metadata':
                d[col] = s.sample_metadata
            else:
                d[col] = getattr(s, col)
        return d

    sample_dicts = [_sample_to_dict(s) for s in samples]

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=sample_dicts,
    ))


@router.get("/{project_id}/samples/{sample_id}", response_model=ApiResponse)
def get_sample(
    project_id: int,
    sample_id: int,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    sample = crud_samples.get_sample(db, sample_id)
    if not sample or sample.project_id != project_id:
        raise HTTPException(status_code=404, detail="样本不存在")

    from crud import crud_annotations
    annotations = crud_annotations.get_sample_annotations(db, sample_id)

    def _sample_to_dict(s):
        if s is None: return None
        d = {}
        for c in s.__table__.columns:
            col = c.name
            if col == 'metadata':
                d[col] = s.sample_metadata
            else:
                d[col] = getattr(s, col)
        return d

    sample_dict = _sample_to_dict(sample)
    ann_dicts = []
    for a in annotations:
        ann_dicts.append({c.name: getattr(a, c.name) for c in a.__table__.columns})

    data = {
        "sample": sample_dict,
        "annotations": ann_dicts,
        "annotation_count": len(ann_dicts),
    }

    return ApiResponse(data=data)
