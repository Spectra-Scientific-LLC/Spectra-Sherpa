"""Compatibility exports for the leaf canonical-DAG execution contract.

The implementation lives in :mod:`spectra_sherpa.execution_contract_vocabulary`
so the live DAG registry can use it without initializing this broad SDK facade.
"""

from spectra_sherpa.execution_contract_vocabulary import (
    FIELD_CONSUMER_PLAN,
    ContractError,
    CustomTrustClass,
    DatasetRankPolicy,
    GroupAccess,
    LifecycleKind,
    ManagedOptimizationEligibility,
    NodeExecutionContract,
    RuntimeFamily,
    SupervisedTask,
    TargetAccess,
    WorkerCapability,
)

__all__ = [
    "ContractError",
    "CustomTrustClass",
    "DatasetRankPolicy",
    "FIELD_CONSUMER_PLAN",
    "GroupAccess",
    "LifecycleKind",
    "ManagedOptimizationEligibility",
    "NodeExecutionContract",
    "RuntimeFamily",
    "SupervisedTask",
    "TargetAccess",
    "WorkerCapability",
]
