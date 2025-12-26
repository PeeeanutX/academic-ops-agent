from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID
import structlog
from supabase import create_client, Client
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings
from src.database.models import (
    Task, TaskStatus, TaskType, DataSource,
    Course, ScheduledBlock, BlockStatus,
    ProductivityLog, ProductivityProfile,
    SyncState, Conflict, Notification
)

logger = structlog.get_logger()


class DatabaseClient:
    def __init__(self):
        settings = get_settings()
        self.client: Client = create_client(
            settings.supabase.url,
            settings.supabase.key
        )
        self._service_client: Optional[Client] = None
        if settings.supabase.service_key:
            self._service_client = create_client(
                settings.supabase.url,
                settings.supabase.service_key
            )

    async def get_course(self, course_id: UUID) -> Optional[Course]:
        result = self.client.table("courses").select("*").eq("id", str(course_id)).single().execute()
        return Course(**result.data) if result.data else None

    async def get_course_by_name(self, name: str) -> Optional[Course]:
        result = self.client.table("courses").select("*").ilike("name", name).single().execute()

    async def get_all_courses(self) -> List[Course]:
        result = self.client.table("courses").select("*").order("name").execute()
        return [Course(**c) for c in result.data]

    async def upsert_course(self, course: Course) -> Course:
        data = course.model_dump(mode="json")
        data["id"] = str(course.id)
        result = self.client.table("courses").upsert(data).execute()
        return Course(**result.data[0])

    async def update_course_difficulty(self, course_id: UUID, difficulty: float) -> None:
        self.client.table("courses").update({
            "difficulty_estimate": difficulty
        }).eq("id", str(course_id)).execute()

    async def get_task(self, task_id: UUID) -> Optional[Task]:
        result = self.client.table("tasks").select("*, courses(name)").eq("id", str(task_id)).single().execute()
        if result.data:
            task_data = result.data
            if task_data.get("courses"):
                task_data["course_name"] = task_data["courses"]["name"]
            del task_data["courses"]
            return Task(**task_data)
        return None

    async def get_task_by_source(self, source: DataSource, source_id: str) -> Optional[Task]:
        """Get task by source and source_id (for deduplication)"""
        result = self.client.table("tasks").select("*").eq("source", source.value).eq("source_id", source_id).single().execute()
        return Task(**result.data) if result.data else None

    async def get_tasks(
            self,
            status: Optional[TaskStatus] = None,
            due_before: Optional[datetime] = None,
            due_after: Optional[datetime] = None,
            course_id: Optional[UUID] = None,
            task_type: Optional[TaskType] = None,
            limit: int = 100
    ) -> List[Task]:
        query = self.client.table("tasks").select("*, courses(name)")

        if status:
            query = query.eq("status", status.value)
        if due_before:
            query = query.eq("due_date", due_before.isoformat())
        if due_after:
            query = query.gte("due_date", due_after.isoformat())
        if course_id:
            query = query.eq("course_id", str(course_id))
        if task_type:
            query = query.eq("task_type", task_type.value)

        result = query.order("due_date").limit(limit).execute()

        tasks = []
        for t in result.data:
            if t.get("courses"):
                t["course_name"] = t["courses"]["name"]
            del t["courses"]
            tasks.append(Task(**t))
        return tasks

    async def get_today_tasks(self) -> List[Task]:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        return await self.get_tasks(due_after=today, due_before=tomorrow)

    async def get_week_tasks(self) -> List[Task]:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = today + timedelta(days=7)
        return await self.get_tasks(due_after=today, due_before=week_end)

    async def get_overdue_tasks(self) -> List[Task]:
        now = datetime.utcnow()
        return await self.get_tasks(status=TaskStatus.PENDING, due_before=now)

    async def get_pending_tasks(self) -> List[Task]:
        return await self.get_tasks(status=TaskStatus.PENDING)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def upsert_task(self, task: Task) -> Task:
        data = task.model_dump(mode="json")
        data["id"] = str(task.id)
        if task.course_id:
            data["course_id"] = str(task.course_id)
            data.pop("course_name", None)
            data["dependencies"] = [str(d) for d in task.dependencies]

            result = self.client.table("tasks").upsert(
                data,
                on_conflict="source,source_id"
            ).execute()
            return Task(**result.data[0])

    async def update_task_status(
            self,
            task_id: UUID,
            status: TaskStatus,
            actual_hours: Optional[float] = None
    ) -> None:
        update_data: Dict[str, Any] = {"status": status.value}

        if status == TaskStatus.COMPLETED:
            update_data["completed_at"] = datetime.utcnow().isoformat()
            if actual_hours:
                update_data["actual_hours"] = actual_hours

        self.client.table("tasks").update(update_data).eq("id", str(task_id)).execute()

    async def snooze_Task(self, task_id: UUID, until: datetime) -> None:
        self.client.table("tasks").update({
            "status": TaskStatus.SNOOZED.value,
            "snoozed_util": until.isoformat()
        }).eq("id", str(task_id)).execute()

    async def update_task_priority(self, task_id: UUID, priority_score: float) -> None:
        self.client.table("tasks").update({
            "priority_score": priority_score
        }).eq("id", str(task_id)).execute()

    async def delete_task(self, task_id: UUID) -> None:
        self.client.table("tasks").delete().eq("id", str(task_id)).execute()

    async def get_scheduled_blocks(
            self,
            start_after: Optional[datetime] = None,
            start_before: Optional[datetime] = None,
            task_id: Optional[UUID] = None
    ) -> List[ScheduledBlock]:
        query = self.client.table("scheduled_blocks").select("*, tasks(title)")

        if start_after:
            query = query.gte("start_time", start_after.isoformat())
        if start_before:
            query = query.lte("start_time", start_before.isoformat())
        if task_id:
            query = query.eq("task_id", str(task_id))

        result = query.order("start_time").execute()

        blocks = []
        for b in result.data:
            if b.get("tasks"):
                b["task_title"] = b["tasks"]["title"]
            del b["tasks"]
            blocks.append(ScheduledBlock(**b))
        return blocks

    async def get_today_schedule(self) -> List[ScheduledBlock]:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        return await self.get_scheduled_blocks(start_after=today, start_before=tomorrow)

    async def create_scheduled_block(self, block: ScheduledBlock) -> ScheduledBlock:
        data = block.model_dump(mode="json")
        data["id"] = str(block.id)
        data["task_id"] = str(block.task_id)
        data.pop("task_title", None)

        result = self.client.table("scheduled_blocks").insert(data).execute()
        return ScheduledBlock(**result.data[0])

    async def update_block_status(self, block_id: UUID, status: BlockStatus) -> None:
        self.client.table("scheduled_blocks").update({
            "status": status.value
        }).eq("id", str(block_id)).execute()

    async def delete_blocks_for_Task(self, task_id: UUID) -> None:
        self.client.table("scheduled_blocks").delete().eq("task_id", str(task_id)).execute()

    async def clear_future_schedule(self, after: datetime) -> None:
        self.client.table("scheduled_blocks").delete().gte("start_time", after.isoformat()).execute()

    async def log_productivity(self, log: ProductivityLog) -> None:
        data = log.model_dump(mode="json")
        data["id"] = str(log.id)
        data["task_id"] = str(log.task_id)
        self.client.table("productivity_logs").insert(data).execute()

    async def get_productivity_logs(self, days: int = 30) -> List[ProductivityLog]:
        since = datetime.utcnow() - timedelta(days=days)
        result = self.client.table("productivity_logs").select("*").gte(
            "started_at", since.isoformat()
        ).execute()
        return [ProductivityLog(**p) for p in result.data]

    async def get_productivity_profile(self) -> ProductivityProfile:
        result = self.client.table("productivity_profile").select("*").limit(1).single().execute()
        return ProductivityProfile(**result.data) if result.data else ProductivityProfile()

    async def update_productivity_profile(self, profile: ProductivityProfile) -> None:
        data = profile.model_dump(mode="json")
        data["last_updated"] = datetime.utcnow().isoformat()

        existing = self.client.table("productivity_profile").select("id").limit(1).single().execute()
        if existing.data:
            self.client.table("productivity_profile").update(data).eq("id", existing.data["id"]).execute()
        else:
            self.client.table("productivity_profile").insert(data).execute()

    async def get_sync_state(self, source: DataSource) -> Optional[SyncState]:
        result = self.client.table("sync_state").select("*").eq("source", source.value).single().execute()
        return SyncState(**result.data) if result.data else None

    async def update_sync_state(self, state: SyncState) -> None:
        data = state.model_dump(mode="json")
        data["source"] = state.source.value
        self.client.table("sync_state").upsert(data).execute()

    async def get_oauth_tokens(self, provider: str) -> Optional[Dict[str, Any]]:
        result = self.client.table("oauth_otkens").select("*").eq("provider", provider).single().execute()
        return result.data if result.data else None

    async def save_oauth_tokens(
        self,
        provider: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
        scopes: List[str]
    ) -> None:
        self.client.table("oauth_tokens").upsert({
            "provider": provider,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at.isoformat(),
            "scopes": scopes
        }).execute()

    async def get_preference(self, key: str) -> Optional[Any]:
        result = self.client.table("user_preferences").select("value").eq("key", key).single().execute()
        return result.data["value"] if result.data else None

    async def set_preference(self, key: str, value: Any) -> None:
        self.client.table("user_preferences").upsert({
            "key": key,
            "value": value
        }).execute()

    async def create_conflict(self, conflict: Conflict) -> None:
        """Record a detected conflict"""
        data = conflict.model_dump(mode="json")
        data["task_a_id"] = str(conflict.task_a_id)
        data["task_b_id"] = str(conflict.task_b_id)
        self.client.table("conflicts").insert(data).execute()

    async def get_unresolved_conflicts(self) -> List[Conflict]:
        result = self.client.table("conflicts").select("*").eq("resolved", False).execute()
        return [Conflict(**c) for c in result.data]

    async def resolve_conflict(self, task_a_id: UUID, task_b_id: UUID, resolution: str) -> None:
        """Mark a conflict as resolved"""
        self.client.table("conflicts").update({
            "resolved": True,
            "resolution": resolution,
            "resolved_at": datetime.utcnow().isoformat()
        }).eq("task_a_id", str(task_a_id)).eq("task_b_id", str(task_b_id)).execute()

    async def create_notification(self, notification: Notification) -> None:
        data = notification.model_dump(mode="json")
        data["id"] = str(notification.id)
        data["task_ids"] = [str(t) for t in notification.tasks]
        self.client.table("notifications").insert(data).execute()

    async def mark_notification_sent(self, notification_id: UUID) -> None:
        self.client.table("notifications").update({
            "sent_at": datetime.utcnow().isoformat()
        }).eq("id", str(notification_id)).execute()


_db_client: Optional[DatabaseClient] = None


def get_db() -> DatabaseClient:
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client
