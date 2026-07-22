"""P2P knowledge-gap broadcast stub — Phase 2 feature.

This module is a stub for mDNS-based peer discovery using the zeroconf library.
In Phase 2, peers on the same LAN will be auto-discovered via mDNS service
announcements and knowledge gaps will be matched with peers who have high mastery
on the required concept, enabling direct device-to-device knowledge transfer
without a central server.
"""

import logging

logger = logging.getLogger(__name__)


def broadcast_knowledge_gap(concept_id: str, student_id: str) -> None:
    """Broadcast that this student needs help with a concept (stub).

    In Phase 2 this will send an mDNS service announcement via zeroconf.

    Args:
        concept_id: The concept the student is struggling with.
        student_id: The learner's identifier.
    """
    logger.info(
        "[P2P stub] Broadcasting knowledge gap: student=%s needs help with concept=%s",
        student_id,
        concept_id,
    )
    print(
        f"[P2P] Broadcasting knowledge gap — student: {student_id}, concept: {concept_id}"
    )


def listen_for_offers() -> list:
    """Listen for incoming peer knowledge-transfer offers (stub).

    In Phase 2 this will browse mDNS for matching service announcements.

    Returns:
        Empty list (stub — no real network call).
    """
    return []


def accept_knowledge_transfer(offer: dict) -> str:
    """Accept a knowledge-transfer offer from a peer (stub).

    Args:
        offer: Dict describing the peer offer (ignored in stub).

    Returns:
        Stub acknowledgement string.
    """
    return "P2P transfer stub — Phase 2 feature"
