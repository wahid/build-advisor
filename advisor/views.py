import json
from collections.abc import Iterator

from django.conf import settings
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from wiki.models import DocumentType
from wiki.search import SearchFilters

from .limits import take_question
from .models import QuestionLog
from .pob import split_build_link
from .prompts import Turn
from .questionlog import record
from .rag import Answer, Event, Source, answer_stream

DAILY_LIMIT_MESSAGE = (
    "The demo has reached today's limit of {limit} questions. "
    "It resets at midnight UTC, so try again tomorrow."
)


class TurnSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, trim_whitespace=True)
    answer = serializers.CharField(max_length=20_000, allow_blank=True, trim_whitespace=True)


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, trim_whitespace=True)
    doc_types = serializers.ListField(
        child=serializers.ChoiceField(choices=DocumentType.values), required=False, default=list
    )
    stream = serializers.BooleanField(required=False, default=True)
    # A Path of Building share code (often 5-20 KB) or a pobb.in / pastebin link.
    build = serializers.CharField(required=False, allow_blank=True, default="", max_length=200_000)
    # Earlier turns of the conversation, oldest first; only the last few are used.
    history = TurnSerializer(many=True, required=False, default=list, max_length=20)


class FeedbackSerializer(serializers.Serializer):
    log_id = serializers.UUIDField()
    rating = serializers.ChoiceField(choices=[1, -1])
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")


class StreamFriendlyNegotiation(BaseContentNegotiation):
    """Don't reject `Accept: text/event-stream`.

    DRF would answer 406 because no renderer produces event streams; the
    stream is a plain StreamingHttpResponse, and errors are rendered as JSON.
    """

    def select_parser(self, request, parsers):  # type: ignore[no-untyped-def]
        return parsers[0]

    def select_renderer(self, request, renderers, format_suffix=None):  # type: ignore[no-untyped-def]
        return renderers[0], renderers[0].media_type


class AskThrottle(AnonRateThrottle):
    scope = "ask"


class FeedbackThrottle(AnonRateThrottle):
    scope = "feedback"


def sse(events: Iterator[Event]) -> Iterator[str]:
    for event in events:
        yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


class AskView(APIView):
    """POST a question; streams Server-Sent Events, or returns JSON with stream=false."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [AskThrottle]
    content_negotiation_class = StreamFriendlyNegotiation

    def post(self, request: Request) -> Response | StreamingHttpResponse:
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not take_question():
            return Response(
                {
                    "detail": DAILY_LIMIT_MESSAGE.format(limit=settings.ASK_DAILY_LIMIT),
                    "code": "daily_limit",
                },
                status=429,
            )
        # A build link pasted into the question is the build to load (it wins over
        # an attached one: it's what the user just pointed at).
        question, link = split_build_link(data["question"])
        options = {
            "filters": SearchFilters(doc_types=tuple(data["doc_types"])),
            "build": link or data["build"],
            "history": [Turn(t["question"], t["answer"]) for t in data["history"]],
        }

        context = {
            "build": options["build"],
            "history": [{"question": t.question, "answer": t.answer} for t in options["history"]],
            "doc_types": list(data["doc_types"]),
        }
        events = record(answer_stream(question, **options), question, **context)

        if not data["stream"]:
            return Response(collect(events))

        response = StreamingHttpResponse(
            sse(events),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # don't let proxies buffer the stream
        return response


def collect(events: Iterator[Event]) -> dict:
    """The JSON answer for stream=false, built from the same events as the stream."""
    result = Answer()
    log_id = ""
    for event in events:
        match event["type"]:
            case "sources":
                result.sources = [Source(**s) for s in event["sources"]]
            case "delta":
                result.text += event["text"]
            case "tool_result":
                result.tools.append(
                    {"name": event["name"], "ok": event["ok"], "preview": event.get("preview", "")}
                )
            case "pob_export":
                result.pob_export = event["code"]
            case "done":
                result.cited = event["cited"]
                result.patch = event["patch"]
                log_id = event.get("log_id", "")
            case "error":
                result.error = event["message"]
    return {**result.as_dict(), "log_id": log_id}


class FeedbackView(APIView):
    """POST a rating (1 or -1) and an optional note for an answer, by its log id."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [FeedbackThrottle]

    def post(self, request: Request) -> Response:
        serializer = FeedbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        updated = QuestionLog.objects.filter(id=data["log_id"]).update(
            rating=data["rating"], feedback=data["feedback"].strip(), rated_at=timezone.now()
        )
        if not updated:
            return Response({"detail": "That answer isn't known."}, status=404)
        return Response({"ok": True})


def frontend(request: HttpRequest) -> HttpResponse:
    """Serve the built React app; in development use the Vite server instead."""
    index = settings.FRONTEND_DIST / "index.html"
    if not index.exists():
        return HttpResponse(
            "The frontend isn't built. In development open http://localhost:5173 "
            "(docker compose runs the Vite dev server); for production run `npm run build`.",
            content_type="text/plain; charset=utf-8",
            status=503,
        )
    return HttpResponse(index.read_text(encoding="utf-8"))
