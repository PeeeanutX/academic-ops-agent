from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    EXAM= "exam"
    ASSIGNMENT = "assignment"
    READING = "reading"
    PROJECT = "project"
    QUIZ = "quiz"
    LAB = "lab"
    DISCUSSION = "discussion"
    OTHER = "other"


class DataSource(str, Enum):
    CALENDAR = "calendar"
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    SYLLABUS = "syllabus"
    MANUAL = "manual"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SNOOZED = "snoozed"


class BlockStatus(str, Enum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class Course(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    code: Optional[str] = None
    difficulty_estimate: float = Field(default=0.5, ge=0, le=1)
    credit_hours: int = Field(default=3)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class Task(BaseModel):
    """Normalized task."""
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: Optional[str] = None
    course_id: Optional[UUID] = None
    course_name: Optional[str] = None
    due_date: datetime
    task_type: TaskType = TaskType.OTHER
    source: DataSource
    source_id: Optional[str] = None
    estimated_hours: float = Field(default=1.0)
    actual_hours: Optional[float] = None
    status: TaskStatus = TaskStatus.PENDING
    priority_score: Optional[float] = None
    dependencies: List[UUID] = Field(default_factory=list)
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None

    class Config:
        from_attributes = True

    @property
    def is_overdue(self) -> bool:
        return self.status == TaskStatus.PENDING and self.due_date < datetime.utcnow()

    @property
    def hours_until_due(self) -> float:
        delta = self.due_date - datetime.utcnow()
        return max(0, delta.total_seconds() / 3600)


class PrioritizedTask(Task):
    priority_score: float
    urgency_score: float = 0.0
    difficulty_score: float = 0.0
    importance_score: float = 0.0
    priority_reasoning: Optional[str] = None


class ScheduledBlock(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    task_title: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: BlockStatus = BlockStatus.SCHEDULED

    class Config:
        from_attributes = True

    @property
    def duration_hours(self) -> float:
        delta = self.end_time - self.start_time
        return delta.total_seconds() / 3600


class CalendarEvent(BaseModel):
    """Raw calendar event from Google Calendar"""
    id: str
    summary: str
    description: Optional[str] = None
    start: datetime
    end: datetime
    location: Optional[str] = None
    recurrence = Optional[List[str]] = None
    source: str = "google_calendar"


class Email(BaseModel):
    """Raw Email from Gmail or Outlook"""
    id: str
    subject: str
    sender: str
    body: str
    received_at: datetime
    labels: List[str] = Field(default_factory=list)
    source: DataSource
    attachments: List[str] = Field(default_factory=list)


class SyllabusItem(BaseModel):
    """Extracted item from a syllabus PDF."""
    title: str
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    task_type: TaskType = TaskType.OTHER
    course_name: Optional[str] = None
    weight: Optional[float] = None
    raw_text: str = ""


class ProductivityLog(BaseModel):
    """Log entry for productivity tracking"""
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    started_at: datetime
    ended_at: Optional[datetime] = None
    focus_rating: Optional[int] = Field(default=None, ge=1, le=5)
    hour_of_day: int
    day_of_week: int  # 0=Monday, 6=Sunday
    notes: Optional[str] = None


class ProductivityProfile(BaseModel):
    """User's learned productivity patterns"""
    productivity_by_hour: Dict[int, float] = Field(default_factory=dict)
    productivity_by_day: Dict[int, float] = Field(default_factory=dict)
    avg_task_completion_ratio: float = 1.0
    preferred_block_length: int = 90
    break_preference: int = 15
    peak_hours: List[int] = Field(default_factory=lambda: [8, 9, 10, 15, 16])
    avoid_hours: List[int] = Field(default_factory=lambda: [13, 14, 22, 23])
    data_points: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class UserPreferences(BaseModel):
    sleep_start_hour: int = 23
    sleep_end_hour: int = 8
    buffer_hours_exam: int = 24
    buffer_hours_assignment: int = 4
    notification_preferences: Dict[str, bool] = Field(default_factory=lambda: {
        "morning_digest": True,
        "weekly_plan": True,
        "deadline_warnings": True,
        "new_task_detected": True
    })
    custom_task_type_weights: Dict[str, float] = Field(default_factory=dict)


class Conflict(BaseModel):
    """Detected conflict between tasks from different sources"""
    task_a_id: UUID
    task_b_id: UUID
    conflict_type: str  # "duplicate", "schedule_overlap", "dependency_cycle"
    resolution: Optional[str] = None
    resolved: bool = False


class Notification(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str  # "morning_digest", "deadline_warning", "new_task", etc.
    title: str
    content: str
    tasks: List[UUID] = Field(default_factory=list)
    priority: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    interactive: bool = True


class SyncState(BaseModel):
    source: DataSource
    last_sync: Optional[datetime] = None
    sync_token: Optional[str] = None
    page_token: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskListResponse(BaseModel):
    tasks: List[Task]
    total: int
    overdue_count: int
    today_count: int
    week_count: int


class ScheduleResponse(BaseModel):
    date: datetime
    blocks: List[ScheduledBlock]
    total_scheduled_hours: float
    free_hours: float
    warnings: List[str] = Field(default_factory=list)
