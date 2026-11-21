"""Async (keep-alive AsyncClient) & Sync (keep-alive Client) Telegram Bot API gateways."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nomark.config import (
    TELEGRAM_API_BASE,
    TELEGRAM_MAX_DOWNLOAD_BYTES,
    TELEGRAM_MAX_UPLOAD_BYTES,
    TELEGRAM_PHOTO_MAX_BYTES,
)


def _extract_cached_file_id(field: str, res: dict[str, Any], fallback: str) -> str:
    result = res.get("result") or {}
    if field == "photo":
        photos = result.get("photo") or []
        return str(photos[-1]["file_id"]) if isinstance(photos, list) and photos else fallback
    obj = result.get(field) or {}
    return str(obj["file_id"]) if isinstance(obj, dict) and obj.get("file_id") else fallback


class AsyncTelegramClient:
    """Non-blocking Telegram Bot API client backed by a pooled keep-alive httpx.AsyncClient.

    Safe for concurrent use under `@modal.concurrent(max_inputs=10)` without blocking the event loop.
    """

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty")
        self._api_url = f"{TELEGRAM_API_BASE}/bot{token}"
        self._timeout = timeout
        self._client: Any = None
        self._loop: Any = None

    def _get_client(self) -> Any:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        loop_changed = self._loop is not None and running_loop is not None and self._loop is not running_loop
        if self._client is None or self._client.is_closed or loop_changed:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
            self._loop = running_loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> AsyncTelegramClient:
        self._get_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _post(self, method: str, *, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        client = self._get_client()
        resp = await client.post(f"{self._api_url}/{method}", json=payload, timeout=timeout or self._timeout)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed: {data}")
        return data

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> int:
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        res = await self._post("sendMessage", payload=body)
        return int(res["result"]["message_id"])

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        import httpx

        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        try:
            await self._post("editMessageText", payload=body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and "message is not modified" in exc.response.text.lower():
                return
            raise

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        body: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            body["text"] = text
        try:
            await self._post("answerCallbackQuery", payload=body)
        except Exception:
            pass

    async def send_cached_file(
        self,
        chat_id: int,
        *,
        delivery_method: str,
        file_id: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        method_map = {
            "document": ("sendDocument", "document"),
            "photo": ("sendPhoto", "photo"),
            "video": ("sendVideo", "video"),
            "audio": ("sendAudio", "audio"),
        }
        api_method, field = method_map.get(delivery_method, ("sendDocument", "document"))
        body: dict[str, Any] = {"chat_id": chat_id, field: file_id, "parse_mode": "HTML"}
        if api_method == "sendVideo":
            body["supports_streaming"] = True
        if caption:
            body["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        res = await self._post(api_method, payload=body, timeout=30.0)
        return _extract_cached_file_id(field, res, file_id)


class SyncTelegramClient:
    """Synchronous keep-alive Telegram client for CPU/GPU media compute workers."""

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty")
        self._api_url = f"{TELEGRAM_API_BASE}/bot{token}"
        self._file_url = f"{TELEGRAM_API_BASE}/file/bot{token}"
        self._timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None or self._client.is_closed:
            import httpx

            self._client = httpx.Client(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
            self._client = None

    def __enter__(self) -> SyncTelegramClient:
        self._get_client()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _post(
        self,
        method: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: Any = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        client = self._get_client()
        resp = client.post(
            f"{self._api_url}/{method}",
            json=json_body,
            data=data,
            files=files,
            timeout=timeout or self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed: {payload}")
        return payload

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> int:
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        res = self._post("sendMessage", json_body=body)
        return int(res["result"]["message_id"])

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        import httpx

        body: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            body["reply_markup"] = reply_markup
        try:
            self._post("editMessageText", json_body=body)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and "message is not modified" in exc.response.text.lower():
                return
            raise

    def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            self._post("deleteMessage", json_body={"chat_id": chat_id, "message_id": message_id})
        except Exception:
            pass

    def send_chat_action(self, chat_id: int, action: str) -> None:
        try:
            self._post("sendChatAction", json_body={"chat_id": chat_id, "action": action})
        except Exception:
            pass

    def download_file(self, file_id: str, dest_path: Path) -> Path:
        info = self._post("getFile", json_body={"file_id": file_id})
        result = info["result"]
        size = result.get("file_size")
        if size is not None and int(size) > TELEGRAM_MAX_DOWNLOAD_BYTES:
            raise ValueError("File exceeds Telegram Bot API 20 MB download limit. Send a direct/Drive/Dropbox link instead.")
        file_path = result["file_path"]
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        client = self._get_client()
        with client.stream("GET", f"{self._file_url}/{file_path}", timeout=120.0) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as handle:
                for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                    handle.write(chunk)
        return dest_path

    @staticmethod
    def _encode_markup(reply_markup: dict[str, Any] | None) -> str | None:
        return json.dumps(reply_markup) if reply_markup is not None else None

    def send_document(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        if file_path.stat().st_size > TELEGRAM_MAX_UPLOAD_BYTES:
            raise ValueError("Output exceeds Telegram Bot API 50 MB upload limit.")
        data: dict[str, Any] = {"chat_id": str(chat_id), "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        if encoded := self._encode_markup(reply_markup):
            data["reply_markup"] = encoded
        with open(file_path, "rb") as handle:
            res = self._post(
                "sendDocument",
                data=data,
                files={"document": (file_path.name, handle, "application/octet-stream")},
                timeout=180.0,
            )
        doc = (res.get("result") or {}).get("document") or {}
        return str(doc["file_id"]) if doc.get("file_id") else None

    def send_photo(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        if file_path.stat().st_size > TELEGRAM_PHOTO_MAX_BYTES:
            return self.send_document(
                chat_id,
                file_path,
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
        data: dict[str, Any] = {"chat_id": str(chat_id), "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        if encoded := self._encode_markup(reply_markup):
            data["reply_markup"] = encoded
        with open(file_path, "rb") as handle:
            res = self._post(
                "sendPhoto",
                data=data,
                files={"photo": (file_path.name, handle, "image/jpeg")},
                timeout=120.0,
            )
        photos = (res.get("result") or {}).get("photo") or []
        return str(photos[-1]["file_id"]) if isinstance(photos, list) and photos else None

    def send_video(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        if file_path.stat().st_size > TELEGRAM_MAX_UPLOAD_BYTES:
            raise ValueError("Output video exceeds Telegram Bot API 50 MB upload limit.")
        data: dict[str, Any] = {
            "chat_id": str(chat_id),
            "parse_mode": "HTML",
            "supports_streaming": "true",
        }
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        if encoded := self._encode_markup(reply_markup):
            data["reply_markup"] = encoded
        with open(file_path, "rb") as handle:
            res = self._post(
                "sendVideo",
                data=data,
                files={"video": (file_path.name, handle, "video/mp4")},
                timeout=240.0,
            )
        vid = (res.get("result") or {}).get("video") or {}
        return str(vid["file_id"]) if vid.get("file_id") else None

    def send_audio(
        self,
        chat_id: int,
        file_path: Path,
        *,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
        reply_markup: dict[str, Any] | None = None,
    ) -> str | None:
        if file_path.stat().st_size > TELEGRAM_MAX_UPLOAD_BYTES:
            raise ValueError("Output audio exceeds Telegram Bot API 50 MB upload limit.")
        data: dict[str, Any] = {"chat_id": str(chat_id), "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        if encoded := self._encode_markup(reply_markup):
            data["reply_markup"] = encoded
        with open(file_path, "rb") as handle:
            res = self._post(
                "sendAudio",
                data=data,
                files={"audio": (file_path.name, handle, "audio/mpeg")},
                timeout=180.0,
            )
        aud = (res.get("result") or {}).get("audio") or {}
        return str(aud["file_id"]) if aud.get("file_id") else None
