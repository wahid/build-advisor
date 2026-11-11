from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .models import Document


@api_view(["GET"])
def health(request: Request) -> Response:
    """Liveness check that also confirms the database is reachable."""
    return Response({"status": "ok", "documents": Document.objects.count()})
