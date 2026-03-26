"""
Rent-a-Relic Market - wRTC Reservation System
AI agents can reserve certified time on vintage machines via MCP or Beacon.
"""

__version__ = "1.0.0"

from .machine_registry import (
    Machine,
    MachineSpecs,
    init_registry_db,
    register_machine,
    get_machine,
    list_machines,
    get_availability,
    set_availability,
    record_attestation,
    seed_demo_machines,
)

from .reservation_system import (
    Reservation,
    ReservationStatus,
    init_reservation_db,
    create_reservation,
    confirm_reservation,
    complete_reservation,
    cancel_reservation,
    get_reservation,
    get_receipt,
    list_reservations,
    get_machine_leaderboard,
)

from .provenance_receipt import (
    ProvenanceReceipt,
    ProvenanceReceiptGenerator,
    generate_dummy_attestation,
    verify_receipt,
)

from .bottube_integration import (
    BottubeVideo,
    RelicBadgeManager,
    create_relic_badge_feed,
    inject_relic_badge_to_rss_item,
)

__all__ = [
    # Version
    "__version__",
    # Machine Registry
    "Machine",
    "MachineSpecs",
    "init_registry_db",
    "register_machine",
    "get_machine",
    "list_machines",
    "get_availability",
    "set_availability",
    "record_attestation",
    "seed_demo_machines",
    # Reservation
    "Reservation",
    "ReservationStatus",
    "init_reservation_db",
    "create_reservation",
    "confirm_reservation",
    "complete_reservation",
    "cancel_reservation",
    "get_reservation",
    "get_receipt",
    "list_reservations",
    "get_machine_leaderboard",
    # Provenance
    "ProvenanceReceipt",
    "ProvenanceReceiptGenerator",
    "generate_dummy_attestation",
    "verify_receipt",
    # BoTTube
    "BottubeVideo",
    "RelicBadgeManager",
    "create_relic_badge_feed",
    "inject_relic_badge_to_rss_item",
]
