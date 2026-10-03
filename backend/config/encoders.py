"""
JSON encoding for hand-built API responses.

DRF's default encoder converts `Decimal` with `float(obj)`, which is lossy:
`Decimal("0.82")` is emitted as `0.81999999999999995`. For an emission factor or
a rupee figure that is simply wrong, and it also makes hand-built responses
inconsistent with serializer-built ones - DRF's `DecimalField` already renders
decimals as strings by default (`COERCE_DECIMAL_TO_STRING`), which is why
`"area_sqm": "50.00"` comes back exact while a plain dict value did not.

This encoder renders every `Decimal` as a string, so one API never reports the
same quantity two different ways.
"""

from decimal import Decimal

from rest_framework.renderers import JSONRenderer
from rest_framework.utils.encoders import JSONEncoder


class DecimalStringJSONEncoder(JSONEncoder):
    """Encode `Decimal` losslessly as a JSON string instead of a float."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


class DecimalStringJSONRenderer(JSONRenderer):
    """DRF JSON renderer using the lossless decimal encoder."""

    encoder_class = DecimalStringJSONEncoder
