#!/usr/bin/env python3
"""
Rent-a-Relic Market API
Flask REST API for the wRTC reservation system.

Endpoints:
- POST /relic/reserve      - Create a new reservation
- GET  /relic/available    - List available machines
- GET  /relic/receipt/<id> - Get a provenance receipt
- GET  /relic/machines     - List all machines
- GET  /relic/machine/<id> - Get machine details
- POST /relic/cancel/<id>  - Cancel a reservation
- GET  /relic/leaderboard  - Get rental leaderboard
- GET  /relic/reservation/<id> - Get reservation details
"""

import json
import time
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from flask import Blueprint, jsonify, request, g

from .machine_registry import (
    init_registry_db,
    get_machine,
    list_machines,
    get_availability,
    seed_demo_machines,
    DB_PATH as MACHINE_DB_PATH,
)
from .reservation_system import (
    init_reservation_db,
    create_reservation,
    confirm_reservation,
    complete_reservation,
    cancel_reservation,
    get_reservation,
    get_receipt as get_receipt_by_id,
    list_reservations,
    get_machine_leaderboard,
    DB_PATH as RESERVATION_DB_PATH,
)


relic_api = Blueprint('relic_api', __name__)

# Ensure database is initialized
def init_dbs():
    """Initialize both databases."""
    init_registry_db(MACHINE_DB_PATH)
    init_reservation_db(RESERVATION_DB_PATH)


# Don't use before_app_first_request on blueprint - use app-level hook instead


# ---------------------------------------------------------------------------
# CORS helper
# ---------------------------------------------------------------------------

def _cors_json(data, status=200):
    """Return JSON response with CORS headers."""
    resp = jsonify(data)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Agent-ID"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp, status


# ---------------------------------------------------------------------------
# Machine Registry Endpoints
# ---------------------------------------------------------------------------

@relic_api.route("/relic/machines", methods=["GET", "OPTIONS"])
def api_list_machines():
    """List all registered machines with optional filters.
    
    Query params:
        status: Filter by status (available, reserved, maintenance, offline)
        arch: Filter by architecture (e.g., "MOS 6502", "Z80", "PowerPC")
        min_uptime: Minimum uptime hours
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    status = request.args.get("status")
    arch = request.args.get("arch")
    min_uptime = int(request.args.get("min_uptime", 0))
    
    machines = list_machines(
        status=status,
        arch=arch,
        min_uptime=min_uptime,
    )
    
    return _cors_json({
        "machines": machines,
        "count": len(machines),
    })


@relic_api.route("/relic/machine/<passport_id>", methods=["GET", "OPTIONS"])
def api_get_machine(passport_id: str):
    """Get detailed information about a specific machine."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    machine = get_machine(passport_id)
    if not machine:
        return _cors_json({"error": "Machine not found"}, 404)
    
    return _cors_json({"machine": machine})


@relic_api.route("/relic/available", methods=["GET", "OPTIONS"])
def api_available_machines():
    """List available machines for reservation.
    
    Query params:
        date: Date to check availability (YYYY-MM-DD, default: today)
        duration: Duration in hours (1, 4, or 24, default: 1)
        arch: Filter by architecture
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    date_str = request.args.get("date")
    duration = int(request.args.get("duration", 1))
    arch = request.args.get("arch")
    
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Get all available machines
    machines = list_machines(status="available", arch=arch)
    
    available = []
    for machine in machines:
        availability = get_availability(machine["passport_id"], date_str)
        
        # Check if requested duration fits
        start_hour = datetime.now().hour + 1
        can_fit = True
        for h in range(start_hour, min(start_hour + duration, 24)):
            if str(h) in availability and not availability[str(h)]:
                can_fit = False
                break
        
        if can_fit:
            machine["available_slots"] = [
                h for h in range(24)
                if str(h) in availability and availability[str(h)]
            ]
            available.append(machine)
    
    return _cors_json({
        "date": date_str,
        "duration_hours": duration,
        "machines": available,
        "count": len(available),
    })


@relic_api.route("/relic/availability/<passport_id>", methods=["GET", "OPTIONS"])
def api_machine_availability(passport_id: str):
    """Get availability calendar for a machine.
    
    Query params:
        start_date: Start date (YYYY-MM-DD, default: today)
        days: Number of days to check (default: 7)
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    start_date_str = request.args.get("start_date")
    days = int(request.args.get("days", 7))
    
    if not start_date_str:
        start_date = datetime.now()
    else:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    
    machine = get_machine(passport_id)
    if not machine:
        return _cors_json({"error": "Machine not found"}, 404)
    
    calendar = {}
    current = start_date
    for _ in range(days):
        date_str = current.strftime("%Y-%m-%d")
        calendar[date_str] = get_availability(passport_id, date_str)
        current += timedelta(days=1)
    
    return _cors_json({
        "passport_id": passport_id,
        "nickname": machine["nickname"],
        "calendar": calendar,
    })


# ---------------------------------------------------------------------------
# Reservation Endpoints
# ---------------------------------------------------------------------------

@relic_api.route("/relic/reserve", methods=["POST", "OPTIONS"])
def api_reserve():
    """Create a new machine reservation.
    
    Request body:
    {
        "machine_passport_id": "MACHINE001",
        "renter_agent_id": "agent_requester_001",
        "start_time": 1711540800.0,  # Unix timestamp
        "duration_hours": 1,  # 1, 4, or 24
        "payment_tx_id": "optional_tx_hash"
    }
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    data = request.get_json()
    if not data:
        return _cors_json({"error": "Missing request body"}, 400)
    
    required_fields = ["machine_passport_id", "renter_agent_id", "start_time", "duration_hours"]
    for field in required_fields:
        if field not in data:
            return _cors_json({"error": f"Missing required field: {field}"}, 400)
    
    # Use agent ID from header if not in body
    renter_agent_id = data.get("renter_agent_id") or request.headers.get("X-Agent-ID", "anonymous")
    
    success, message, reservation = create_reservation(
        machine_passport_id=data["machine_passport_id"],
        renter_agent_id=renter_agent_id,
        start_time=float(data["start_time"]),
        duration_hours=int(data["duration_hours"]),
        rtc_payment_tx=data.get("payment_tx_id", ""),
    )
    
    if not success:
        return _cors_json({"error": message}, 400)
    
    return _cors_json({
        "success": True,
        "message": message,
        "reservation": reservation,
    }, 201)


@relic_api.route("/relic/reservation/<reservation_id>", methods=["GET", "OPTIONS"])
def api_get_reservation(reservation_id: str):
    """Get details of a specific reservation."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    reservation = get_reservation(reservation_id)
    if not reservation:
        return _cors_json({"error": "Reservation not found"}, 404)
    
    return _cors_json({"reservation": reservation})


@relic_api.route("/relic/reservation/<reservation_id>/complete", methods=["POST", "OPTIONS"])
def api_complete_reservation(reservation_id: str):
    """Complete a reservation and generate provenance receipt.
    
    Request body:
    {
        "output_hash": "sha256_of_computation_output",
        "computation_description": "Description of what was computed"
    }
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    data = request.get_json()
    if not data:
        return _cors_json({"error": "Missing request body"}, 400)
    
    output_hash = data.get("output_hash", "")
    computation_description = data.get("computation_description", "")
    
    success, message, receipt = complete_reservation(
        reservation_id=reservation_id,
        output_hash=output_hash,
        computation_description=computation_description,
    )
    
    if not success:
        return _cors_json({"error": message}, 400)
    
    return _cors_json({
        "success": True,
        "message": message,
        "receipt": receipt,
    })


@relic_api.route("/relic/cancel/<reservation_id>", methods=["POST", "OPTIONS"])
def api_cancel_reservation(reservation_id: str):
    """Cancel a reservation and refund escrow."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    success, message = cancel_reservation(reservation_id)
    
    if not success:
        return _cors_json({"error": message}, 400)
    
    return _cors_json({
        "success": True,
        "message": message,
    })


@relic_api.route("/relic/reservations", methods=["GET", "OPTIONS"])
def api_list_reservations():
    """List reservations with optional filters.
    
    Query params:
        renter_agent_id: Filter by renter
        machine_passport_id: Filter by machine
        status: Filter by status
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    renter_agent_id = request.args.get("renter_agent_id")
    machine_passport_id = request.args.get("machine_passport_id")
    status = request.args.get("status")
    
    reservations = list_reservations(
        renter_agent_id=renter_agent_id,
        machine_passport_id=machine_passport_id,
        status=status,
    )
    
    return _cors_json({
        "reservations": reservations,
        "count": len(reservations),
    })


# ---------------------------------------------------------------------------
# Receipt Endpoints
# ---------------------------------------------------------------------------

@relic_api.route("/relic/receipt/<receipt_id>", methods=["GET", "OPTIONS"])
def api_get_receipt(receipt_id: str):
    """Get a provenance receipt by ID."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    receipt = get_receipt_by_id(receipt_id)
    if not receipt:
        return _cors_json({"error": "Receipt not found"}, 404)
    
    return _cors_json({"receipt": receipt})


# ---------------------------------------------------------------------------
# Leaderboard Endpoint
# ---------------------------------------------------------------------------

@relic_api.route("/relic/leaderboard", methods=["GET", "OPTIONS"])
def api_leaderboard():
    """Get the rental leaderboard (most popular machines)."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    leaderboard = get_machine_leaderboard()
    
    return _cors_json({
        "leaderboard": leaderboard,
        "count": len(leaderboard),
    })


# ---------------------------------------------------------------------------
# MCP-compatible Endpoint (for AI agents)
# ---------------------------------------------------------------------------

@relic_api.route("/relic/mcp/reserve", methods=["POST", "OPTIONS"])
def api_mcp_reserve():
    """MCP-compatible reservation endpoint for AI agents.
    
    Same as /relic/reserve but with MCP-style response format.
    """
    if request.method == "OPTIONS":
        return _cors_json({})
    
    data = request.get_json()
    if not data:
        return _cors_json({"error": "Missing request body"}, 400)
    
    # MCP requires these fields
    machine_id = data.get("machine_id") or data.get("machine_passport_id")
    duration = int(data.get("duration_hours", data.get("duration", 1)))
    agent_id = data.get("agent_id") or request.headers.get("X-Agent-ID", "anonymous")
    start_time = float(data.get("start_time", time.time()))
    
    if not machine_id:
        return _cors_json({"error": "Missing machine_id"}, 400)
    
    success, message, reservation = create_reservation(
        machine_passport_id=machine_id,
        renter_agent_id=agent_id,
        start_time=start_time,
        duration_hours=duration,
    )
    
    if not success:
        return _cors_json({
            "success": False,
            "error": message,
        }, 400)
    
    return _cors_json({
        "success": True,
        "result": {
            "reservation_id": reservation["reservation_id"],
            "session_id": reservation["session_id"],
            "machine_passport_id": reservation["machine_passport_id"],
            "ssh_credentials": reservation.get("ssh_credentials", {}),
            "start_time": reservation["start_time"],
            "duration_hours": reservation["duration_hours"],
            "cost_rtc": reservation["rtc_amount"],
        },
    })


@relic_api.route("/relic/mcp/available", methods=["GET", "OPTIONS"])
def api_mcp_available():
    """MCP-compatible endpoint to list available machines."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    arch = request.args.get("arch")
    min_uptime = int(request.args.get("min_uptime", 0))
    
    machines = list_machines(status="available", arch=arch, min_uptime=min_uptime)
    
    return _cors_json({
        "success": True,
        "result": {
            "machines": [
                {
                    "id": m["passport_id"],
                    "nickname": m["nickname"],
                    "architecture": m["specs"]["arch"],
                    "model": m["specs"]["model"],
                    "price_rtc_per_hour": m["rental_price_per_hour"],
                    "uptime_hours": m["uptime_hours"],
                }
                for m in machines
            ]
        }
    })


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

@relic_api.route("/relic/health", methods=["GET", "OPTIONS"])
def api_health():
    """Health check endpoint."""
    if request.method == "OPTIONS":
        return _cors_json({})
    
    return _cors_json({
        "status": "ok",
        "timestamp": time.time(),
        "version": "1.0.0",
    })


def create_app():
    """Create Flask application for relic market."""
    from flask import Flask
    
    app = Flask(__name__)
    app.register_blueprint(relic_api)
    
    # Initialize databases
    init_dbs()
    
    return app


if __name__ == "__main__":
    import os
    
    init_dbs()
    seed_demo_machines()
    
    app = create_app()
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
