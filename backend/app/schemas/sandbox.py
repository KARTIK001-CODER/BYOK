from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SandboxScenarioMetadata(BaseModel):
    """Metadata describing a deterministic sandbox scenario."""

    scenario_id: str
    name: str
    description: str
    category: str


class SandboxSimulationRequest(BaseModel):
    """Request payload to execute one or more sandbox simulation scenarios."""

    scenario_id: str | None = Field(
        default=None,
        description="Scenario ID to simulate. If None or 'ALL', runs all deterministic scenarios.",
    )


class SandboxSimulationResult(BaseModel):
    """Deterministic result for an individual simulated remediation scenario.

    Strictly non-executing and local.
    """

    model_config = ConfigDict(from_attributes=True)

    scenario_id: str
    scenario_name: str
    simulated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_fixture_data: dict[str, Any]
    simulated_conditions: dict[str, Any]
    policy_validation_results: dict[str, Any]
    expected_outcome: str
    actual_outcome: str
    passed: bool
    execution_performed: bool = False
    disclaimer: str = (
        "Deterministic local simulation only. "
        "No real infrastructure, cloud APIs, shell commands, or mutations were executed."
    )


class SandboxSimulationResponse(BaseModel):
    """Aggregated response containing execution results for simulated sandbox scenarios."""

    results: list[SandboxSimulationResult]
    total_scenarios: int
    passed_scenarios: int
    all_passed: bool
    is_simulation: bool = True
    disclaimer: str = (
        "TracePilot Sandbox Simulation results are synthetic and local. "
        "Automated remediation execution remains strictly prohibited."
    )
