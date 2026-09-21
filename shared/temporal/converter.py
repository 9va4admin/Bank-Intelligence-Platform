"""
Pydantic v2 DataConverter for Temporal workers.

temporalio==1.7.1 does not ship temporalio.contrib.pydantic, so we build
our own.  The converter intercepts JSON deserialization and, when the type
hint is a pydantic.BaseModel subclass, calls model_validate() instead of
relying on Temporal's default dict pass-through.

Usage:
    from shared.temporal.converter import pydantic_data_converter

    client = await Client.connect(
        address,
        namespace=namespace,
        data_converter=pydantic_data_converter,
    )
"""
import datetime as _dt
import decimal as _decimal
from typing import Any, Type

import pydantic
from temporalio.converter import (
    AdvancedJSONEncoder,
    BinaryNullPayloadConverter,
    BinaryProtoPayloadConverter,
    CompositePayloadConverter,
    DataConverter,
    JSONPlainPayloadConverter,
    JSONProtoPayloadConverter,
    JSONTypeConverter,
)


class _PydanticV2TypeConverter(JSONTypeConverter):
    """Converts dict → pydantic.BaseModel using model_validate()."""

    def to_typed_value(self, hint: Type, value: Any) -> Any:
        if (
            isinstance(hint, type)
            and issubclass(hint, pydantic.BaseModel)
            and isinstance(value, dict)
        ):
            return hint.model_validate(value)
        # ISO strings back into date/datetime fields of plain dataclasses (the stock decoder raises
        # "Unserializable type ... datetime.date", failing the workflow task).
        if hint is _dt.datetime and isinstance(value, str):
            return _dt.datetime.fromisoformat(value)
        if hint is _dt.date and isinstance(value, str):
            return _dt.date.fromisoformat(value)
        return JSONTypeConverter.Unhandled


class _PydanticJSONEncoder(AdvancedJSONEncoder):
    """Encode pydantic v2 models via model_dump(mode="json") so date/datetime/Decimal
    fields serialise (the stock encoder raises "Object of type date is not JSON
    serializable", which made workflow tasks fail and retry forever)."""

    def default(self, o: Any) -> Any:
        if isinstance(o, pydantic.BaseModel):
            return o.model_dump(mode="json")
        if isinstance(o, (_dt.datetime, _dt.date)):
            return o.isoformat()
        if isinstance(o, _decimal.Decimal):
            return str(o)
        return super().default(o)


class _PydanticPayloadConverter(CompositePayloadConverter):
    """Drop-in replacement for DefaultPayloadConverter with pydantic v2 support."""

    def __init__(self) -> None:
        super().__init__(
            BinaryNullPayloadConverter(),
            BinaryProtoPayloadConverter(),
            JSONProtoPayloadConverter(),
            JSONPlainPayloadConverter(
                encoder=_PydanticJSONEncoder,
                custom_type_converters=[_PydanticV2TypeConverter()],
            ),
        )


pydantic_data_converter = DataConverter(
    payload_converter_class=_PydanticPayloadConverter,
)
