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
from typing import Any, Type

import pydantic
from temporalio.converter import (
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
        return JSONTypeConverter.Unhandled


class _PydanticPayloadConverter(CompositePayloadConverter):
    """Drop-in replacement for DefaultPayloadConverter with pydantic v2 support."""

    def __init__(self) -> None:
        super().__init__(
            BinaryNullPayloadConverter(),
            BinaryProtoPayloadConverter(),
            JSONProtoPayloadConverter(),
            JSONPlainPayloadConverter(
                custom_type_converters=[_PydanticV2TypeConverter()]
            ),
        )


pydantic_data_converter = DataConverter(
    payload_converter_class=_PydanticPayloadConverter,
)
