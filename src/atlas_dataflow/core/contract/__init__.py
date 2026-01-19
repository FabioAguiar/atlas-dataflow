"""Atlas DataFlow — Contract (core).

Componentes canônicos para o **Internal Contract v1**:
 - parsing (YAML/JSON)
 - validação estrutural
 - hashing canônico (rastreabilidade)
"""

from .errors import (  # noqa: F401
    ContractError,
    ContractPathMissingError,
    ContractFileNotFoundError,
    ContractParseError,
    UnsupportedContractFormatError,
    ContractValidationError,
)

from .hashing import compute_contract_hash  # noqa: F401
from .loader import load_contract  # noqa: F401
from .schema import InternalContractV1, validate_internal_contract_v1  # noqa: F401
