from dataclasses import dataclass

from fastapi.responses import JSONResponse

from payload_validator import ValidationFailure


@dataclass(frozen=True)
class PublicError:
    status_code: int
    error_type: str
    error_code: str
    message: str

    def response(self, *, errors: list[dict[str, str]] | None = None) -> JSONResponse:
        content = {
            "error_type": self.error_type,
            "error_code": self.error_code,
            "message": self.message,
        }
        if errors is not None:
            content["errors"] = errors
        return JSONResponse(status_code=self.status_code, content=content)


DATASET_NOT_FOUND = PublicError(
    status_code=404,
    error_type="dataset_not_found",
    error_code="DATASET_NOT_FOUND",
    message="The requested dataset is not available.",
)

RELEASE_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="release_unavailable",
    error_code="RELEASE_UNAVAILABLE",
    message="No active release is available for this dataset.",
)

REGISTRY_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="registry_unavailable",
    error_code="REGISTRY_UNAVAILABLE",
    message="The registry is not currently available.",
)

CONTRACT_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="contract_unavailable",
    error_code="CONTRACT_UNAVAILABLE",
    message="The active contract for this dataset is temporarily unavailable.",
)

PUBLIC_CONTRACT_UNAVAILABLE = PublicError(
    status_code=503,
    error_type="contract_unavailable",
    error_code="PUBLIC_CONTRACT_UNAVAILABLE",
    message="The public contract for this dataset is temporarily unavailable.",
)

INVALID_PAYLOAD = PublicError(
    status_code=422,
    error_type="invalid_payload",
    error_code="INVALID_PAYLOAD",
    message="The inference payload is invalid.",
)

INFERENCE_FAILURE = PublicError(
    status_code=503,
    error_type="inference_failure",
    error_code="INFERENCE_FAILURE",
    message="Inference is temporarily unavailable.",
)

UNEXPECTED_ERROR = PublicError(
    status_code=500,
    error_type="unexpected_error",
    error_code="UNEXPECTED_ERROR",
    message="The request could not be completed.",
)


def public_error_response(public_error: PublicError) -> JSONResponse:
    return public_error.response()


def validation_error_response(failures: list[ValidationFailure]) -> JSONResponse:
    safe_errors = [
        {
            "error_code": failure.error_code,
            "message": failure.message,
            "field": failure.field,
            "violation": failure.violation,
        }
        for failure in failures
    ]
    return INVALID_PAYLOAD.response(errors=safe_errors)

