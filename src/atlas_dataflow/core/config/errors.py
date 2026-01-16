"""
Atlas DataFlow — Config Errors

Exceções canônicas usadas pelo Loader de Config/Contrato.

Essas exceções:
- são tipadas (evitar ValueError genérico)
- expressam violações arquiteturais explícitas
- são usadas por core, APIs e testes
"""


class ConfigError(Exception):
    """Erro base para problemas relacionados à configuração."""


class DefaultsNotFoundError(ConfigError):
    """Disparado quando o arquivo de defaults não é encontrado."""


class UnsupportedConfigFormatError(ConfigError):
    """Disparado quando a extensão do arquivo de config não é suportada."""


class InvalidConfigRootTypeError(ConfigError):
    """Disparado quando o root do config não é um dict/map."""


class ConfigTypeConflictError(ConfigError):
    """Disparado quando ocorre conflito de tipos durante o deep-merge."""
