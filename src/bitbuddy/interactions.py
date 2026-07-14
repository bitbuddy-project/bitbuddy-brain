from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str


@dataclass(frozen=True)
class UserQuestion:
    id: str
    header: str
    question: str
    options: tuple[QuestionOption, ...]


@dataclass(frozen=True)
class QuestionRequest:
    id: str
    questions: tuple[UserQuestion, ...]


def parse_question_request(arguments: dict[str, object]) -> QuestionRequest:
    raw_questions = arguments.get("questions")
    if not isinstance(raw_questions, list) or not 1 <= len(raw_questions) <= 3:
        raise ValueError("request_user_input requires between one and three questions.")

    questions: list[UserQuestion] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_questions):
        if not isinstance(raw, dict):
            raise ValueError("Each user question must be an object.")
        question_id = str(raw.get("id") or f"question_{index + 1}").strip()[:80]
        header = str(raw.get("header") or "Question").strip()[:40]
        prompt = str(raw.get("question") or "").strip()[:1000]
        raw_options = raw.get("options")
        if not question_id or question_id in seen_ids:
            raise ValueError("Question ids must be non-empty and unique.")
        if not prompt:
            raise ValueError("Every user question requires question text.")
        if not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 3:
            raise ValueError("Every user question requires two or three choices.")

        options: list[QuestionOption] = []
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                raise ValueError("Question choices must be objects.")
            label = str(raw_option.get("label") or "").strip()[:120]
            description = str(raw_option.get("description") or "").strip()[:500]
            if not label:
                raise ValueError("Every question choice requires a label.")
            options.append(QuestionOption(label=label, description=description))

        seen_ids.add(question_id)
        questions.append(UserQuestion(id=question_id, header=header, question=prompt, options=tuple(options)))

    return QuestionRequest(id=str(uuid.uuid4()), questions=tuple(questions))


def question_request_to_json(request: QuestionRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "questions": [
            {
                "id": question.id,
                "header": question.header,
                "question": question.question,
                "options": [
                    {"label": option.label, "description": option.description}
                    for option in question.options
                ],
            }
            for question in request.questions
        ],
    }


def validate_question_answers(request: QuestionRequest, raw_answers: object) -> dict[str, str]:
    if not isinstance(raw_answers, dict):
        raise ValueError("Question answers must be an object keyed by question id.")
    answers: dict[str, str] = {}
    for question in request.questions:
        answer = str(raw_answers.get(question.id) or "").strip()[:2000]
        if not answer:
            raise ValueError(f"An answer is required for `{question.id}`.")
        answers[question.id] = answer
    return answers


def question_answers_tool_result(request: QuestionRequest, answers: dict[str, str]) -> str:
    return json.dumps(
        {
            "interaction_id": request.id,
            "answers": [
                {
                    "id": question.id,
                    "question": question.question,
                    "answer": answers[question.id],
                }
                for question in request.questions
            ],
        },
        indent=2,
    )
