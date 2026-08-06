from pydantic import BaseModel, ConfigDict


class SerializedResponse(BaseModel):
    """Declare fields with server defaults as present in serialized API responses."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
