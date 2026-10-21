from typing import Any

from pydantic import BaseModel


class TopologyNode(BaseModel):
    id: str
    kind: str
    label: str
    subtitle: str | None
    status: str | None
    entity_id: int
    meta: dict[str, Any]


class TopologyEdge(BaseModel):
    source: str
    target: str
    relation: str


class Topology(BaseModel):
    nodes: list[TopologyNode]
    edges: list[TopologyEdge]
    truncated: bool
