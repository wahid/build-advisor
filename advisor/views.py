import json
from collections.abc import Iterator

from django.conf import settings
from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from rest_framework import serializers
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from wiki.models import DocumentType
from wiki.search import SearchFilters

from .rag import Event, answer, answer_stream


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, trim_whitespace=True)
    doc_types = serializers.ListField(
        child=serializers.ChoiceField(choices=DocumentType.values), required=False, default=list
    )
    stream = serializers.BooleanField(required=False, default=True)


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
        filters = SearchFilters(doc_types=tuple(data["doc_types"]))

        if not data["stream"]:
            return Response(answer(data["question"], filters=filters).as_dict())

        response = StreamingHttpResponse(
            sse(answer_stream(data["question"], filters=filters)),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # don't let proxies buffer the stream
        return response


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
