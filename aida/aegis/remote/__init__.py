from aida.aegis.remote.models import (
    RemoteAccessClassification,
    RemoteIntrusionAssessment,
    RemoteLogonEvent,
    RemoteSessionEvidence,
    RemoteSupportAuthorization,
    RemoteToolEvidence,
)


def __getattr__(name: str):
    if name == "AegisRemoteIntrusionService":
        from aida.aegis.remote.service import AegisRemoteIntrusionService
        return AegisRemoteIntrusionService
    if name == "RemoteSupportService":
        from aida.aegis.remote.support import RemoteSupportService
        return RemoteSupportService
    raise AttributeError(name)

__all__ = [
    "AegisRemoteIntrusionService",
    "RemoteAccessClassification",
    "RemoteIntrusionAssessment",
    "RemoteLogonEvent",
    "RemoteSessionEvidence",
    "RemoteSupportAuthorization",
    "RemoteSupportService",
    "RemoteToolEvidence",
]
