"""
MCP Tools for Rent-a-Relic Market
AI agents can use these tools to reserve time on vintage machines.
"""

import json
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass

# Import from relic market
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from relic_market.machine_registry import (
    get_machine,
    list_machines,
    get_availability,
)
from relic_market.reservation_system import (
    create_reservation,
    complete_reservation,
    cancel_reservation,
    get_reservation,
    get_receipt as get_receipt_by_id,
    list_reservations,
)
from relic_market.provenance_receipt import verify_receipt


@dataclass
class MCPReservationResult:
    """Result of a reservation operation."""
    success: bool
    reservation_id: Optional[str] = None
    session_id: Optional[str] = None
    machine_passport_id: Optional[str] = None
    ssh_credentials: Optional[Dict] = None
    start_time: Optional[float] = None
    duration_hours: Optional[int] = None
    cost_rtc: Optional[float] = None
    error: Optional[str] = None


@dataclass
class MCPMachineInfo:
    """Information about a machine."""
    passport_id: str
    nickname: str
    architecture: str
    model: str
    manufacturer: str
    year: int
    cpu_clock: float
    ram_kb: int
    uptime_hours: int
    price_per_hour: float
    status: str
    attestation_count: int


def mcp_list_available_machines(
    architecture: Optional[str] = None,
    min_uptime_hours: int = 0,
) -> List[MCPMachineInfo]:
    """
    List all available machines for reservation.
    
    Args:
        architecture: Filter by CPU architecture (e.g., "MOS 6502", "Z80", "PowerPC")
        min_uptime_hours: Minimum machine uptime to include
    
    Returns:
        List of available machines with their specifications
    """
    machines = list_machines(
        status="available",
        arch=architecture,
        min_uptime=min_uptime_hours,
    )
    
    result = []
    for m in machines:
        result.append(MCPMachineInfo(
            passport_id=m["passport_id"],
            nickname=m["nickname"],
            architecture=m["specs"]["arch"],
            model=m["specs"]["model"],
            manufacturer=m["specs"]["manufacturer"],
            year=m["specs"]["manufacture_year"],
            cpu_clock=m["specs"]["cpu_clock_mhz"],
            ram_kb=m["specs"]["ram_kb"],
            uptime_hours=m["uptime_hours"],
            price_per_hour=m["rental_price_per_hour"],
            status=m["status"],
            attestation_count=m["attestation_count"],
        ))
    
    return result


def mcp_reserve_machine(
    machine_id: str,
    agent_id: str,
    duration_hours: int = 1,
    start_time: Optional[float] = None,
) -> MCPReservationResult:
    """
    Reserve time on a vintage machine.
    
    Args:
        machine_id: The machine's passport ID
        agent_id: Your agent identifier
        duration_hours: Reservation duration (1, 4, or 24 hours)
        start_time: Unix timestamp for reservation start (default: now + 1 hour)
    
    Returns:
        Reservation details including SSH credentials
    """
    if start_time is None:
        start_time = time.time() + 3600  # Default: 1 hour from now
    
    success, message, reservation = create_reservation(
        machine_passport_id=machine_id,
        renter_agent_id=agent_id,
        start_time=start_time,
        duration_hours=duration_hours,
    )
    
    if not success:
        return MCPReservationResult(success=False, error=message)
    
    return MCPReservationResult(
        success=True,
        reservation_id=reservation["reservation_id"],
        session_id=reservation["session_id"],
        machine_passport_id=reservation["machine_passport_id"],
        ssh_credentials=reservation.get("ssh_credentials", {}),
        start_time=reservation["start_time"],
        duration_hours=reservation["duration_hours"],
        cost_rtc=reservation["rtc_amount"],
    )


def mcp_complete_session(
    reservation_id: str,
    output_hash: str,
    computation_description: str,
) -> Dict[str, Any]:
    """
    Complete a reservation and receive a provenance receipt.
    
    Args:
        reservation_id: Your reservation ID
        output_hash: SHA256 hash of your computation output
        computation_description: What you computed
    
    Returns:
        Provenance receipt with attestation proof
    """
    success, message, receipt = complete_reservation(
        reservation_id=reservation_id,
        output_hash=output_hash,
        computation_description=computation_description,
    )
    
    if not success:
        return {"success": False, "error": message}
    
    return {
        "success": True,
        "receipt": receipt,
    }


def mcp_cancel_reservation(reservation_id: str) -> Dict[str, Any]:
    """
    Cancel a reservation and get a refund.
    
    Args:
        reservation_id: The reservation to cancel
    
    Returns:
        Cancellation confirmation
    """
    success, message = cancel_reservation(reservation_id)
    
    if not success:
        return {"success": False, "error": message}
    
    return {
        "success": True,
        "message": message,
    }


def mcp_get_receipt(receipt_id: str) -> Dict[str, Any]:
    """
    Retrieve a provenance receipt.
    
    Args:
        receipt_id: The receipt ID
    
    Returns:
        Receipt details with verification info
    """
    receipt = get_receipt_by_id(receipt_id)
    
    if not receipt:
        return {"success": False, "error": "Receipt not found"}
    
    return {
        "success": True,
        "receipt": receipt,
    }


def mcp_verify_receipt(receipt_id: str, machine_public_key: str) -> Dict[str, Any]:
    """
    Verify a provenance receipt's signature.
    
    Args:
        receipt_id: The receipt to verify
        machine_public_key: The machine's Ed25519 public key
    
    Returns:
        Verification result
    """
    receipt = get_receipt_by_id(receipt_id)
    
    if not receipt:
        return {"success": False, "error": "Receipt not found"}
    
    is_valid = verify_receipt(receipt, machine_public_key)
    
    return {
        "success": True,
        "receipt_id": receipt_id,
        "signature_valid": is_valid,
        "verified_at": time.time(),
    }


def mcp_check_availability(
    machine_id: str,
    date: str,
) -> Dict[str, Any]:
    """
    Check a machine's availability for a specific date.
    
    Args:
        machine_id: The machine's passport ID
        date: Date in YYYY-MM-DD format
    
    Returns:
        Availability slots for that day
    """
    machine = get_machine(machine_id)
    if not machine:
        return {"success": False, "error": "Machine not found"}
    
    availability = get_availability(machine_id, date)
    
    available_hours = [
        int(h) for h, is_avail in availability.items()
        if is_avail
    ]
    
    return {
        "success": True,
        "machine_id": machine_id,
        "nickname": machine["nickname"],
        "date": date,
        "available_hours": available_hours,
        "unavailable_hours": [
            int(h) for h, is_avail in availability.items()
            if not is_avail
        ],
    }


def mcp_get_machine_info(machine_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific machine.
    
    Args:
        machine_id: The machine's passport ID
    
    Returns:
        Machine details including specs and attestation history
    """
    machine = get_machine(machine_id)
    
    if not machine:
        return {"success": False, "error": "Machine not found"}
    
    return {
        "success": True,
        "machine": {
            "passport_id": machine["passport_id"],
            "nickname": machine["nickname"],
            "specs": machine["specs"],
            "photos": machine["photos"],
            "uptime_hours": machine["uptime_hours"],
            "attestation_count": machine["attestation_count"],
            "attestation_history": machine["attestation_history"][-10:],  # Last 10
            "status": machine["status"],
            "price_per_hour": machine["rental_price_per_hour"],
            "ssh_enabled": machine["ssh_access_enabled"],
            "api_endpoint": machine["api_endpoint"],
            "owner": machine["owner_agent_id"],
            "ed25519_public_key": machine["ed25519_public_key"],
        },
    }


# MCP Tool Definitions (for use with MCP-compatible servers)
MCP_TOOLS = [
    {
        "name": "relic_list_available",
        "description": "List all available vintage machines for rent",
        "input_schema": {
            "type": "object",
            "properties": {
                "architecture": {
                    "type": "string",
                    "description": "Filter by CPU architecture (e.g., 'MOS 6502', 'Z80', 'PowerPC')"
                },
                "min_uptime_hours": {
                    "type": "integer",
                    "description": "Minimum uptime hours to include",
                    "default": 0
                }
            }
        }
    },
    {
        "name": "relic_reserve",
        "description": "Reserve time on a vintage machine",
        "input_schema": {
            "type": "object",
            "required": ["machine_id", "agent_id", "duration_hours"],
            "properties": {
                "machine_id": {
                    "type": "string",
                    "description": "Machine passport ID"
                },
                "agent_id": {
                    "type": "string",
                    "description": "Your agent identifier"
                },
                "duration_hours": {
                    "type": "integer",
                    "enum": [1, 4, 24],
                    "description": "Reservation duration"
                },
                "start_time": {
                    "type": "number",
                    "description": "Unix timestamp for start time (default: 1 hour from now)"
                }
            }
        }
    },
    {
        "name": "relic_complete",
        "description": "Complete a reservation and get provenance receipt",
        "input_schema": {
            "type": "object",
            "required": ["reservation_id", "output_hash", "computation_description"],
            "properties": {
                "reservation_id": {
                    "type": "string",
                    "description": "Your reservation ID"
                },
                "output_hash": {
                    "type": "string",
                    "description": "SHA256 hash of computation output"
                },
                "computation_description": {
                    "type": "string",
                    "description": "Description of what was computed"
                }
            }
        }
    },
    {
        "name": "relic_cancel",
        "description": "Cancel a reservation",
        "input_schema": {
            "type": "object",
            "required": ["reservation_id"],
            "properties": {
                "reservation_id": {
                    "type": "string",
                    "description": "Reservation to cancel"
                }
            }
        }
    },
    {
        "name": "relic_get_receipt",
        "description": "Retrieve a provenance receipt",
        "input_schema": {
            "type": "object",
            "required": ["receipt_id"],
            "properties": {
                "receipt_id": {
                    "type": "string",
                    "description": "Receipt ID"
                }
            }
        }
    },
    {
        "name": "relic_verify_receipt",
        "description": "Verify a receipt's signature",
        "input_schema": {
            "type": "object",
            "required": ["receipt_id", "machine_public_key"],
            "properties": {
                "receipt_id": {
                    "type": "string",
                    "description": "Receipt to verify"
                },
                "machine_public_key": {
                    "type": "string",
                    "description": "Machine's Ed25519 public key"
                }
            }
        }
    },
    {
        "name": "relic_check_availability",
        "description": "Check machine availability for a date",
        "input_schema": {
            "type": "object",
            "required": ["machine_id", "date"],
            "properties": {
                "machine_id": {
                    "type": "string",
                    "description": "Machine passport ID"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                }
            }
        }
    },
    {
        "name": "relic_machine_info",
        "description": "Get detailed machine information",
        "input_schema": {
            "type": "object",
            "required": ["machine_id"],
            "properties": {
                "machine_id": {
                    "type": "string",
                    "description": "Machine passport ID"
                }
            }
        }
    },
]


def handle_mcp_tool(tool_name: str, arguments: Dict) -> Dict:
    """Handle an MCP tool call."""
    if tool_name == "relic_list_available":
        return {
            "success": True,
            "machines": [
                {
                    "id": m.passport_id,
                    "nickname": m.nickname,
                    "architecture": m.architecture,
                    "model": m.model,
                    "price_per_hour": m.price_per_hour,
                    "uptime_hours": m.uptime_hours,
                }
                for m in mcp_list_available_machines(
                    arguments.get("architecture"),
                    arguments.get("min_uptime_hours", 0),
                )
            ]
        }
    
    elif tool_name == "relic_reserve":
        result = mcp_reserve_machine(
            machine_id=arguments["machine_id"],
            agent_id=arguments["agent_id"],
            duration_hours=arguments["duration_hours"],
            start_time=arguments.get("start_time"),
        )
        return {
            "success": result.success,
            "reservation_id": result.reservation_id,
            "session_id": result.session_id,
            "ssh_credentials": result.ssh_credentials,
            "cost_rtc": result.cost_rtc,
            "error": result.error,
        }
    
    elif tool_name == "relic_complete":
        return mcp_complete_session(
            reservation_id=arguments["reservation_id"],
            output_hash=arguments["output_hash"],
            computation_description=arguments["computation_description"],
        )
    
    elif tool_name == "relic_cancel":
        return mcp_cancel_reservation(arguments["reservation_id"])
    
    elif tool_name == "relic_get_receipt":
        return mcp_get_receipt(arguments["receipt_id"])
    
    elif tool_name == "relic_verify_receipt":
        return mcp_verify_receipt(
            arguments["receipt_id"],
            arguments["machine_public_key"],
        )
    
    elif tool_name == "relic_check_availability":
        return mcp_check_availability(
            arguments["machine_id"],
            arguments["date"],
        )
    
    elif tool_name == "relic_machine_info":
        return mcp_get_machine_info(arguments["machine_id"])
    
    else:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}


if __name__ == "__main__":
    # Demo
    print("=== Rent-a-Relic MCP Tools Demo ===\n")
    
    # List available machines
    print("Available Machines:")
    machines = mcp_list_available_machines()
    for m in machines:
        print(f"  {m.passport_id}: {m.nickname} ({m.architecture}) - {m.price_per_hour} RTC/hr")
    
    if machines:
        print("\n--- Making a reservation ---")
        result = mcp_reserve_machine(
            machine_id=machines[0].passport_id,
            agent_id="agent_demo_001",
            duration_hours=1,
        )
        print(f"Success: {result.success}")
        if result.success:
            print(f"Reservation ID: {result.reservation_id}")
            print(f"SSH Host: {result.ssh_credentials.get('host')}")
            print(f"Cost: {result.cost_rtc} RTC")
        else:
            print(f"Error: {result.error}")
