from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict

from models import (
    UserRole, ProjectType, ProjectStatus, SampleStatus,
    TaskStatus, AnnotationStatus, QualityStatus, ConsistencyLevel
)


class UserBase(BaseModel):
    username: str
    display_name: str
    email: Optional[str] = None
    role: UserRole = UserRole.ANNOTATOR


class UserCreate(UserBase):
    pass


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    created_at: datetime


class UserLite(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: UserRole


class LabelSpecBase(BaseModel):
    name: str
    description: Optional[str] = None
    value_type: str
    options: Optional[List[Dict[str, Any]]] = None
    required: bool = True
    sort_order: int = 0
    parent_id: Optional[int] = None


class LabelSpecCreate(LabelSpecBase):
    pass


class LabelSpec(LabelSpecBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    created_at: datetime


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    project_type: ProjectType
    required_annotators: int = 2
    samples_per_task: int = 50
    quality_sample_rate: float = 0.1
    consistency_threshold: float = 0.8
    lock_timeout_seconds: int = 1800


class ProjectCreate(ProjectBase):
    creator_id: int
    label_specs: Optional[List[LabelSpecCreate]] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    required_annotators: Optional[int] = None
    samples_per_task: Optional[int] = None
    quality_sample_rate: Optional[float] = None
    consistency_threshold: Optional[float] = None


class Project(ProjectBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: ProjectStatus
    creator_id: int
    creator: Optional[UserLite] = None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(Project):
    label_specs: List[LabelSpec] = []
    sample_count: int = 0
    task_count: int = 0
    completed_sample_count: int = 0


class SampleBase(BaseModel):
    external_id: Optional[str] = None
    content: str
    content_url: Optional[str] = None
    sample_metadata: Optional[Dict[str, Any]] = Field(default=None, alias='metadata')


class SampleCreate(SampleBase):
    pass


class SampleBatchCreate(BaseModel):
    samples: List[SampleCreate]


class Sample(SampleBase):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    project_id: int
    status: SampleStatus
    consistency_score: Optional[float] = None
    consistency_level: Optional[ConsistencyLevel] = None
    final_annotation: Optional[Dict[str, Any]] = None
    version: int
    created_at: datetime
    updated_at: datetime


class SampleWithAnnotations(Sample):
    annotations: List["Annotation"] = []


class AnnotationBase(BaseModel):
    content: Dict[str, Any]
    time_spent_seconds: Optional[int] = None
    comment: Optional[str] = None


class AnnotationCreate(AnnotationBase):
    sample_id: int
    task_id: Optional[int] = None


class AnnotationSubmit(AnnotationBase):
    pass


class Annotation(AnnotationBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    sample_id: int
    annotator_id: int
    task_id: Optional[int] = None
    status: AnnotationStatus
    version: int
    is_from_rework: bool
    created_at: datetime
    updated_at: datetime


class AnnotationWithAnnotator(Annotation):
    annotator: Optional[UserLite] = None


class TaskSampleBase(BaseModel):
    sort_order: int = 0


class TaskSample(TaskSampleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    task_id: int
    sample_id: int
    is_completed: bool
    completed_at: Optional[datetime] = None
    sample: Optional[Sample] = None


class TaskBase(BaseModel):
    note: Optional[str] = None
    deadline: Optional[datetime] = None


class TaskCreate(TaskBase):
    project_id: int
    assignee_id: int
    task_type: str = "annotation"
    sample_count: int = 50


class TaskAssign(BaseModel):
    project_id: int
    assignee_id: int
    sample_count: int = 50
    task_type: str = "annotation"


class Task(TaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    assignee_id: int
    status: TaskStatus
    task_type: str
    locked_by: Optional[int] = None
    locked_at: Optional[datetime] = None
    progress: float
    assignee: Optional[UserLite] = None
    created_at: datetime
    updated_at: datetime


class TaskDetail(Task):
    samples: List[TaskSample] = []


class TaskClaim(BaseModel):
    project_id: int
    annotator_id: int
    sample_count: Optional[int] = None


class LockTask(BaseModel):
    task_id: int
    user_id: int


class UnlockTask(BaseModel):
    task_id: int
    user_id: int


class ConflictRecordBase(BaseModel):
    pass


class ConflictRecord(ConflictRecordBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    sample_id: int
    involved_annotator_ids: List[int]
    conflict_fields: List[str]
    consistency_score: float
    resolved: bool
    resolver_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    sample: Optional[Sample] = None
    created_at: datetime


class ConflictResolve(BaseModel):
    resolver_id: int
    resolution_note: Optional[str] = None
    final_annotation: Dict[str, Any]


class ReviewTaskBase(BaseModel):
    pass


class ReviewTask(ReviewTaskBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    conflict_id: int
    sample_id: int
    assignee_id: int
    status: TaskStatus
    locked_by: Optional[int] = None
    locked_at: Optional[datetime] = None
    resolution: Optional[Dict[str, Any]] = None
    resolution_comment: Optional[str] = None
    assignee: Optional[UserLite] = None
    created_at: datetime
    updated_at: datetime


class ReviewTaskSubmit(BaseModel):
    checker_id: int
    resolution: Dict[str, Any]
    resolution_comment: Optional[str] = None


class QualityCheckBase(BaseModel):
    comment: Optional[str] = None


class QualityCheckCreate(QualityCheckBase):
    project_id: int
    sample_id: int
    checker_id: int
    annotation_id: Optional[int] = None


class QualityCheckSubmit(BaseModel):
    checker_id: int
    status: QualityStatus
    quality_score: float
    error_fields: Optional[List[str]] = None
    comment: Optional[str] = None


class QualityCheck(QualityCheckBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    sample_id: int
    checker_id: int
    annotation_id: Optional[int] = None
    status: QualityStatus
    quality_score: Optional[float] = None
    error_fields: Optional[List[str]] = None
    is_sampled: bool
    checker: Optional[UserLite] = None
    created_at: datetime
    updated_at: datetime


class QualitySampleRequest(BaseModel):
    project_id: int
    checker_id: int
    sample_count: Optional[int] = None
    sample_rate: Optional[float] = None


class ReworkRecordBase(BaseModel):
    pass


class ReworkComplete(BaseModel):
    new_annotation_content: Optional[dict] = None
    new_annotation_id: Optional[int] = None
    time_spent_seconds: Optional[int] = None
    rework_annotator_id: Optional[int] = None


class ReworkRecordCreate(BaseModel):
    project_id: int
    sample_id: int
    original_annotator_id: int
    reason: str
    issue_fields: Optional[List[str]] = None
    quality_check_id: Optional[int] = None
    rework_annotator_id: Optional[int] = None


class ReworkRecord(ReworkRecordBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    sample_id: int
    quality_check_id: Optional[int] = None
    original_annotator_id: int
    rework_annotator_id: Optional[int] = None
    reason: str
    issue_fields: Optional[List[str]] = None
    status: TaskStatus
    completed_at: Optional[datetime] = None
    sample: Optional[Sample] = None
    created_at: datetime
    updated_at: datetime


class AnnotatorProgress(BaseModel):
    annotator_id: int
    annotator_name: str
    project_id: int
    project_name: str
    total_assigned: int
    completed: int
    in_progress: int
    rejected: int
    rework_count: int
    quality_score_avg: Optional[float] = None
    avg_time_per_sample: Optional[float] = None
    consistency_rate: Optional[float] = None
    last_active_at: Optional[datetime] = None


class ProjectStats(BaseModel):
    project_id: int
    project_name: str
    total_samples: int
    pending_samples: int
    in_progress_samples: int
    submitted_samples: int
    conflict_samples: int
    approved_samples: int
    rejected_samples: int
    progress_percentage: float
    total_tasks: int
    active_tasks: int
    completed_tasks: int
    active_annotators: int
    avg_consistency_score: Optional[float] = None
    avg_quality_score: Optional[float] = None


class ExportJobBase(BaseModel):
    export_format: str = "json"
    include_metadata: bool = True
    filters: Optional[Dict[str, Any]] = None


class ExportJobCreate(ExportJobBase):
    project_id: int
    creator_id: int


class ExportJob(ExportJobBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    creator_id: int
    status: str
    file_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class ResultSummary(BaseModel):
    project_id: int
    project_name: str
    project_type: str
    total_samples: int
    approved_samples: int
    approval_rate: float
    total_annotations: int
    avg_consistency_score: Optional[float] = None
    avg_quality_score: Optional[float] = None
    label_distribution: Dict[str, Dict[str, int]] = {}
    top_labels: List[Dict[str, Any]] = []
    annotator_rankings: List[Dict[str, Any]] = []


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
    items: List[Any]


class ApiResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[Any] = None


class ConsistencyCheckResult(BaseModel):
    sample_id: int
    is_consistent: bool
    consistency_score: float
    consistency_level: ConsistencyLevel
    conflict_fields: List[str]
    majority_annotation: Optional[Dict[str, Any]] = None
    annotations: List[AnnotationWithAnnotator] = []
