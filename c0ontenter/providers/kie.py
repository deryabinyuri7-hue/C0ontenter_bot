import json

import httpx

from c0ontenter.providers.base import ProviderTask


class KieProviderError(RuntimeError):
    pass


class KieGenerationProvider:
    """Adapter for the KIE endpoints supplied with the selected models."""

    base_url = "https://api.kie.ai"
    image_create_path = "/api/v1/jobs/createTask"
    video_create_path = "/api/v1/runway/generate"
    video_status_path = "/api/v1/runway/record-detail"
    image_sizes = {"1:1": "square_hd", "9:16": "portrait_16_9", "16:9": "landscape_16_9"}
    video_aspects = {"9:16", "16:9"}

    def __init__(
        self,
        *,
        api_key: str,
        image_model_id: str,
        image_status_path: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._image_model_id = image_model_id
        self._image_status_path = image_status_path
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def create_image_task(self, *, prompt: str, aspect_ratio: str) -> str:
        try:
            size = self.image_sizes[aspect_ratio]
        except KeyError as exc:
            raise ValueError("Image aspect ratio must be one of: 1:1, 9:16, 16:9") from exc
        payload = {"model": self._image_model_id, "input": {"prompt": prompt, "image_size": size}}
        return await self._create_task(self.image_create_path, payload)

    async def create_video_task(self, *, prompt: str, aspect_ratio: str) -> str:
        if aspect_ratio not in self.video_aspects:
            raise ValueError("Video aspect ratio must be one of: 9:16, 16:9")
        # KIE's supplied Runway request schema does not define a model field.
        # Do not guess an undocumented model field into the payload.
        payload = {
            "prompt": prompt,
            "duration": 5,
            "quality": "720p",
            "aspectRatio": aspect_ratio,
            "waterMark": "",
        }
        return await self._create_task(self.video_create_path, payload)

    async def get_task_status(self, *, kind: str, task_id: str) -> ProviderTask:
        if kind == "image" and not self._image_status_path:
            raise KieProviderError("KIE_IMAGE_TASK_STATUS_PATH must be configured")
        path = self._image_status_path if kind == "image" else self.video_status_path
        response = await self._client.get(path, params={"taskId": task_id})
        body = await self._body(response)
        data = body.get("data") or {}
        state = str(data.get("state", "unknown"))
        if kind == "video":
            result_url = (data.get("videoInfo") or {}).get("videoUrl")
        else:
            raw_result = data.get("resultJson")
            try:
                result_url = (json.loads(raw_result or "{}").get("resultUrls") or [None])[0]
            except (TypeError, json.JSONDecodeError):
                result_url = None
        return ProviderTask(
            task_id=str(data.get("taskId", task_id)),
            state=state,
            result_url=result_url,
            error_message=data.get("failMsg"),
        )

    async def _create_task(self, path: str, payload: dict[str, object]) -> str:
        response = await self._client.post(path, json=payload)
        body = await self._body(response)
        task_id = (body.get("data") or {}).get("taskId")
        if not task_id:
            raise KieProviderError("KIE did not return taskId")
        return str(task_id)

    async def _body(self, response: httpx.Response) -> dict[str, object]:
        try:
            body = response.json()
        except ValueError as exc:
            raise KieProviderError("KIE returned invalid JSON") from exc
        if response.is_error or body.get("code") != 200:
            raise KieProviderError(str(body.get("msg", f"KIE HTTP {response.status_code}")))
        return body
