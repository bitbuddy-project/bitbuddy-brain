from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


class ClientDisconnected(Exception):
    pass


class ChatCancelled(Exception):
    pass


@dataclass
class ActiveChatRun:
    chat_id: str
    mode: str
    model: str | None
    prompt_messages: list[dict[str, str]]
    thinking_enabled: bool = True
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    return_greeting_text: str = ""
    conversation_gap_minutes: int | None = None
    conversation_gap_label: str = ""
    assistant_message_id: int | None = None
    assistant_text: str = ""
    thinking_text: str = ""
    status: str = "running"
    error: str = ""
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    context_usage: dict[str, Any] = field(default_factory=dict)
    subscribers: list[queue.Queue[dict[str, Any]]] = field(default_factory=list)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    permission_request: dict[str, Any] | None = None
    permission_response: threading.Event = field(default_factory=threading.Event)
    permission_granted: bool = False
    question_request: Any | None = None
    question_answers: dict[str, str] = field(default_factory=dict)
    question_response: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()

        with self.lock:
            self.subscribers.append(subscriber)

            subscriber.put(
                {
                    "kind": "snapshot",
                    "content": self.assistant_text,
                    "thinking": self.thinking_text,
                    "context_usage": self.context_usage,
                }
            )

            if self.context_usage:
                subscriber.put(
                    {
                        "kind": "context_usage",
                        "usage": self.context_usage,
                        **self.context_usage,
                    }
                )

            for event in self.tool_events:
                subscriber.put(event)

            if self.permission_request is not None:
                subscriber.put(
                    {
                        "kind": "permission_request",
                        "tool": self.permission_request.get("tool", ""),
                        "reason": self.permission_request.get("reason", "BitBuddy needs your permission to proceed."),
                        "arguments": self.permission_request.get("arguments", {}),
                    }
                )

            if self.question_request is not None:
                from ..interactions import question_request_to_json

                subscriber.put(
                    {
                        "kind": "question_request",
                        "request": question_request_to_json(self.question_request),
                    }
                )

            if self.status == "complete":
                subscriber.put({"done": True})
            elif self.status == "failed":
                subscriber.put(
                    {
                        "kind": "error",
                        "text": self.error or "Generation failed.",
                        "done": True,
                    }
                )
            elif self.status == "cancelled":
                subscriber.put({"kind": "cancelled", "text": "Stopped.", "done": True})

        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self.lock:
            subscribers = list(self.subscribers)

        for subscriber in subscribers:
            subscriber.put(event)

    def cancel(self) -> None:
        self.cancel_requested.set()

        with self.lock:
            self.status = "cancelled"

        self.broadcast({"kind": "cancelled", "text": "Stopped.", "done": True})


ACTIVE_CHAT_RUNS: dict[str, ActiveChatRun] = {}
ACTIVE_CHAT_RUNS_LOCK = threading.Lock()

LAST_PROMPT_USAGE_BY_CHAT_ID: dict[str, dict[str, Any]] = {}
LAST_PROMPT_USAGE_LOCK = threading.Lock()

LAST_PROJECT_BY_CHAT_ID: dict[str, str] = {}
LAST_PROJECT_LOCK = threading.Lock()


def active_chat_run(chat_id: str) -> ActiveChatRun | None:
    with ACTIVE_CHAT_RUNS_LOCK:
        run = ACTIVE_CHAT_RUNS.get(chat_id)

    if run and run.status == "running":
        return run

    return None


def register_chat_run(run: ActiveChatRun) -> None:
    with ACTIVE_CHAT_RUNS_LOCK:
        ACTIVE_CHAT_RUNS[run.chat_id] = run


def unregister_chat_run(chat_id: str, run: ActiveChatRun) -> None:
    with ACTIVE_CHAT_RUNS_LOCK:
        if ACTIVE_CHAT_RUNS.get(chat_id) is run:
            ACTIVE_CHAT_RUNS.pop(chat_id, None)


def remember_chat_project(chat_id: str, project_id: str) -> None:
    if not chat_id or not project_id:
        return

    with LAST_PROJECT_LOCK:
        LAST_PROJECT_BY_CHAT_ID[chat_id] = project_id


def remembered_chat_project(chat_id: str, projects: list[Any]) -> Any | None:
    with LAST_PROJECT_LOCK:
        project_id = LAST_PROJECT_BY_CHAT_ID.get(chat_id, "")

    if not project_id:
        return None

    return next((project for project in projects if project.id == project_id), None)
