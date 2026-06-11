from typing import List, Optional, Dict, Any
import os
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from config import settings
from schemas import (
    ExportJobCreate, ExportJob, ResultSummary,
    ApiResponse, PaginatedResponse
)
from crud import crud_export, crud_projects, crud_users

router = APIRouter(prefix="/export", tags=["结果输出"])


def _execute_export_background(job_id: int, database_url: str):
    from database import SessionLocal, engine
    from sqlalchemy.orm import sessionmaker
    from config import settings as s

    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        crud_export.execute_export_job(db, job_id)
    finally:
        db.close()


@router.post("/jobs", response_model=ApiResponse, status_code=201)
def create_export_job(
    job: ExportJobCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, job.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    creator = crud_users.get_user(db, job.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="创建者不存在")

    valid_formats = ['json', 'csv', 'excel']
    if job.export_format.lower() not in valid_formats:
        return ApiResponse(
            code=400,
            message=f"不支持的导出格式，可选: {', '.join(valid_formats)}",
            data=None,
        )

    db_job = crud_export.create_export_job(db, job)

    background_tasks.add_task(
        _execute_export_background,
        db_job.id,
        settings.DATABASE_URL,
    )

    return ApiResponse(data=db_job, message="导出任务已创建，正在后台执行")


@router.get("/jobs", response_model=ApiResponse)
def list_export_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[int] = None,
    creator_id: Optional[int] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
):
    skip = (page - 1) * page_size
    jobs = crud_export.get_export_jobs(
        db, project_id, creator_id, status_filter, skip, page_size
    )
    total = len(jobs) if skip == 0 else 9999
    total_pages = (total + page_size - 1) // page_size

    return ApiResponse(data=PaginatedResponse(
        total=total, page=page, page_size=page_size,
        total_pages=total_pages, items=jobs,
    ))


@router.get("/jobs/{job_id}", response_model=ApiResponse)
def get_export_job(job_id: int, db: Session = Depends(get_db)):
    job = crud_export.get_export_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    return ApiResponse(data=job)


@router.post("/jobs/{job_id}/execute", response_model=ApiResponse)
def execute_export_job_now(job_id: int, db: Session = Depends(get_db)):
    job = crud_export.get_export_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    if job.status == 'processing':
        return ApiResponse(
            code=400,
            message="导出任务正在执行中，请稍后再试",
            data=job,
        )

    result = crud_export.execute_export_job(db, job_id)
    if not result:
        raise HTTPException(status_code=500, detail="导出任务执行失败")

    if result.status == 'failed':
        return ApiResponse(
            code=500,
            message=f"导出失败: {result.error_message}",
            data=result,
        )

    return ApiResponse(data=result, message="导出任务执行成功")


@router.get("/jobs/{job_id}/download")
def download_export_file(job_id: int, db: Session = Depends(get_db)):
    job = crud_export.get_export_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    if job.status != 'completed':
        raise HTTPException(
            status_code=400,
            detail=f"导出任务未完成，当前状态: {job.status}"
        )

    if not job.file_path or not os.path.exists(job.file_path):
        raise HTTPException(status_code=404, detail="导出文件不存在")

    filename = os.path.basename(job.file_path)
    project = crud_projects.get_project(db, job.project_id)
    if project:
        from services.export_service import generate_filename
        filename = generate_filename(job.project_id, job.export_format)

    return FileResponse(
        path=job.file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/projects/{project_id}/summary", response_model=ApiResponse)
def get_result_summary(
    project_id: int,
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    summary = crud_export.get_result_summary(db, project_id)
    if not summary:
        raise HTTPException(status_code=500, detail="结果汇总数据获取失败")

    return ApiResponse(data=summary, message="结果汇总获取成功")


@router.get("/projects/{project_id}/preview")
def preview_export_data(
    project_id: int,
    format: str = Query("json", description="预览格式: json 或 csv"),
    include_metadata: bool = Query(True, description="是否包含元数据"),
    sample_limit: int = Query(10, ge=1, le=100, description="预览样本数量"),
    db: Session = Depends(get_db),
):
    project = crud_projects.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from models import Sample
    samples = (
        db.query(Sample)
        .filter(Sample.project_id == project_id)
        .order_by(Sample.id.asc())
        .limit(sample_limit)
        .all()
    )

    sample_ids = [s.id for s in samples]

    from crud import crud_annotations
    from models import Annotation
    annotations = []
    if sample_ids:
        annotations = (
            db.query(Annotation)
            .filter(Annotation.sample_id.in_(sample_ids))
            .order_by(Annotation.sample_id.asc(), Annotation.created_at.asc())
            .all()
        )

    label_specs = (
        db.query(crud_projects.LabelSpec)
        .filter(crud_projects.LabelSpec.project_id == project_id)
        .order_by(crud_projects.LabelSpec.sort_order.asc())
        .all()
    ) if hasattr(crud_projects, 'LabelSpec') else []

    from services.export_service import export_to_json, export_to_csv

    fmt = format.lower()
    if fmt == 'csv':
        content = export_to_csv(samples, annotations, project, include_metadata, label_specs)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="preview_project_{project_id}.csv"'
            }
        )
    else:
        content = export_to_json(samples, annotations, project, include_metadata, label_specs)
        import json
        return JSONResponse(content=json.loads(content))
