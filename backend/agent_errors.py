"""Safe codes only: never persist provider text or arbitrary exception messages."""

from backend.domain import PermanentError, TransientError


class AgentProtocolError(PermanentError):
    code = "agent_protocol_error"


class AgentToolError(PermanentError):
    code = "agent_tool_rejected"


class AgentBudgetError(PermanentError):
    code = "agent_budget_exceeded"


class AgentRefused(PermanentError):
    code = "agent_refused"


class AgentConfigurationError(PermanentError):
    code = "agent_configuration_error"


class ProviderTransientError(TransientError):
    code = "provider_transient_error"


AGENT_ERROR_CODES = frozenset(
    {
        cls.code
        for cls in (
            AgentProtocolError,
            AgentToolError,
            AgentBudgetError,
            AgentRefused,
            AgentConfigurationError,
            ProviderTransientError,
        )
    }
)
