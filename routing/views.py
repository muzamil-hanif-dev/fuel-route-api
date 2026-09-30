"""
The route endpoint:  POST /api/route/   { "start": "...", "finish": "..." }

Flow:
  1. Validate the body with RouteRequestSerializer.
  2. Run the pipeline (geocode -> OSRM -> fuel algorithm -> GeoJSON).
  3. Return JSON, or a clean error with a fitting HTTP status code.
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer
from .services.fuel import InfeasibleRoute
from .services.geocoding import GeocodingError
from .services.pipeline import build_route_plan
from .services.routing_osrm import RoutingError


class RouteView(APIView):
    """Takes a start + finish, returns the route, fuel stops, and total cost."""

    def post(self, request):
        # 1. Validate input (missing/blank fields -> automatic 400).
        serializer = RouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data["start"]
        finish = serializer.validated_data["finish"]

        # 2. Run the pipeline, mapping each failure to a sensible status code.
        try:
            result = build_route_plan(start, finish)
        except GeocodingError as exc:
            # A place name couldn't be found -> the client's input was bad (400).
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except InfeasibleRoute as exc:
            # Route is valid but can't be fueled within range (422 = unprocessable).
            return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingError as exc:
            # The upstream routing service failed (502 = bad gateway).
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        # 3. Success.
        return Response(result, status=status.HTTP_200_OK)
