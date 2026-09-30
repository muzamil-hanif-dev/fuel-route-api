"""
Request validation for the route endpoint.

A DRF "serializer" here acts as an input guard: it confirms the request body has
a non-empty `start` and `finish` (both text) before the view does any real work.
If they're missing/blank, DRF returns a clean 400 error automatically.
"""
from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, trim_whitespace=True)
    finish = serializers.CharField(max_length=200, trim_whitespace=True)
