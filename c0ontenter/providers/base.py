from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderTask:
    task_id: str
    state: str
    result_url: str | None = None
    error_message: str | None = None


class GenerationProvider(Protocol):
    async def create_image_task(self, *, prompt: str, aspect_ratio: str) -> str: ...

    async def create_video_task(self, *, prompt: str, aspect_ratio: str) -> str: ...

    async def get_task_status(self, *, kind: str, task_id: str) -> ProviderTask: ...
