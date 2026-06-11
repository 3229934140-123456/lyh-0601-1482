from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Boolean, Enum, JSON
from sqlalchemy.orm import relationship

from database import Base


class UserRole(str, PyEnum):
    ANNOTATOR = "annotator"
    QUALITY_CHECKER = "quality_checker"
    ADMIN = "admin"


class ProjectType(str, PyEnum):
    TEXT = "text"
    IMAGE = "image"


class ProjectStatus(str, PyEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SampleStatus(str, PyEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    ANNOTATING = "annotating"
    SUBMITTED = "submitted"
    CONFLICT = "conflict"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskStatus(str, PyEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    REVIEWING = "reviewing"
    COMPLETED = "completed"


class AnnotationStatus(str, PyEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CONFLICT = "conflict"
    APPROVED = "approved"
    REJECTED = "rejected"


class QualityStatus(str, PyEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REWORK = "needs_rework"


class ConsistencyLevel(str, PyEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=True)
    display_name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.ANNOTATOR, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    annotations = relationship("Annotation", back_populates="annotator", foreign_keys="Annotation.annotator_id")
    tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")
    quality_checks = relationship("QualityCheck", back_populates="checker", foreign_keys="QualityCheck.checker_id")
    created_projects = relationship("Project", back_populates="creator", foreign_keys="Project.creator_id")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text, nullable=True)
    project_type = Column(Enum(ProjectType), nullable=False)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.DRAFT, nullable=False, index=True)
    required_annotators = Column(Integer, default=2, nullable=False)
    samples_per_task = Column(Integer, default=50, nullable=False)
    quality_sample_rate = Column(Float, default=0.1, nullable=False)
    consistency_threshold = Column(Float, default=0.8, nullable=False)
    lock_timeout_seconds = Column(Integer, default=1800, nullable=False)

    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    creator = relationship("User", back_populates="created_projects", foreign_keys=[creator_id])

    samples = relationship("Sample", back_populates="project", cascade="all, delete-orphan")
    label_specs = relationship("LabelSpec", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")
    annotations = relationship("Annotation", back_populates="project", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LabelSpec(Base):
    __tablename__ = "label_specs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    value_type = Column(String(50), nullable=False)
    options = Column(JSON, nullable=True)
    required = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    parent_id = Column(Integer, ForeignKey("label_specs.id"), nullable=True)

    project = relationship("Project", back_populates="label_specs")
    children = relationship("LabelSpec", remote_side=[id])

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    external_id = Column(String(200), nullable=True, index=True)
    content = Column(Text, nullable=False)
    content_url = Column(String(500), nullable=True)
    sample_metadata = Column('metadata', JSON, nullable=True)
    status = Column(Enum(SampleStatus), default=SampleStatus.PENDING, nullable=False, index=True)
    consistency_score = Column(Float, nullable=True)
    consistency_level = Column(Enum(ConsistencyLevel), nullable=True)
    final_annotation = Column(JSON, nullable=True)
    version = Column(Integer, default=1, nullable=False)

    project = relationship("Project", back_populates="samples")
    annotations = relationship("Annotation", back_populates="sample", cascade="all, delete-orphan")
    task_assignments = relationship("TaskSample", back_populates="sample", cascade="all, delete-orphan")
    conflicts = relationship("ConflictRecord", back_populates="sample", cascade="all, delete-orphan")
    quality_checks = relationship("QualityCheck", back_populates="sample", cascade="all, delete-orphan")
    rework_records = relationship("ReworkRecord", back_populates="sample", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    task_type = Column(String(50), default="annotation", nullable=False)
    locked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    deadline = Column(DateTime, nullable=True)
    progress = Column(Float, default=0.0, nullable=False)
    note = Column(Text, nullable=True)

    project = relationship("Project", back_populates="tasks")
    assignee = relationship("User", back_populates="tasks", foreign_keys=[assignee_id])
    samples = relationship("TaskSample", back_populates="task", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class TaskSample(Base):
    __tablename__ = "task_samples"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    task = relationship("Task", back_populates="samples")
    sample = relationship("Sample", back_populates="task_assignments")


class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    annotator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    content = Column(JSON, nullable=False)
    status = Column(Enum(AnnotationStatus), default=AnnotationStatus.DRAFT, nullable=False, index=True)
    time_spent_seconds = Column(Integer, nullable=True)
    version = Column(Integer, default=1, nullable=False)
    comment = Column(Text, nullable=True)
    is_from_rework = Column(Boolean, default=False, nullable=False)

    project = relationship("Project", back_populates="annotations")
    sample = relationship("Sample", back_populates="annotations")
    annotator = relationship("User", back_populates="annotations", foreign_keys=[annotator_id])

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ConflictRecord(Base):
    __tablename__ = "conflict_records"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    involved_annotator_ids = Column(JSON, nullable=False)
    conflict_fields = Column(JSON, nullable=False)
    consistency_score = Column(Float, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    resolver_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    sample = relationship("Sample", back_populates="conflicts")
    review_tasks = relationship("ReviewTask", back_populates="conflict", cascade="all, delete-orphan")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    conflict_id = Column(Integer, ForeignKey("conflict_records.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    locked_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    resolution = Column(JSON, nullable=True)
    resolution_comment = Column(Text, nullable=True)

    conflict = relationship("ConflictRecord", back_populates="review_tasks")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class QualityCheck(Base):
    __tablename__ = "quality_checks"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    checker_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    annotation_id = Column(Integer, ForeignKey("annotations.id"), nullable=True, index=True)
    status = Column(Enum(QualityStatus), default=QualityStatus.PENDING, nullable=False, index=True)
    quality_score = Column(Float, nullable=True)
    error_fields = Column(JSON, nullable=True)
    comment = Column(Text, nullable=True)
    is_sampled = Column(Boolean, default=True, nullable=False)

    sample = relationship("Sample", back_populates="quality_checks")
    checker = relationship("User", back_populates="quality_checks", foreign_keys=[checker_id])

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ReworkRecord(Base):
    __tablename__ = "rework_records"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    sample_id = Column(Integer, ForeignKey("samples.id"), nullable=False, index=True)
    quality_check_id = Column(Integer, ForeignKey("quality_checks.id"), nullable=True)
    original_annotator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rework_annotator_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reason = Column(Text, nullable=False)
    issue_fields = Column(JSON, nullable=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)

    sample = relationship("Sample", back_populates="rework_records")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    export_format = Column(String(50), default="json", nullable=False)
    include_metadata = Column(Boolean, default=True, nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    file_path = Column(String(500), nullable=True)
    filters = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
