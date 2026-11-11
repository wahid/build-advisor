import json
from collections.abc import Iterator

from django.http import StreamingHttpResponse
from rest_framework import serializers
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
