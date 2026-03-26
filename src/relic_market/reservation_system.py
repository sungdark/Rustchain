"""
Reservation System for Rent-a-Relic Market
Handles machine reservations with RTC payment and escrow.
"""

import json
import sqlite3
import hashlib
import time
import uuid
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum

try:
    from .machine_registry import (
        get_machine,
        update_machine_status,
        get_availability,
        set_availability,
        record_attestation,
    )
    from .provenance_receipt import (
        ProvenanceReceiptGenerator,
        ProvenanceReceipt,
        generate_dummy_attestation,
    )
except ImportError:
    # Allow running as standalone script
    from machine_registry import (
        get_machine,
        update_machine_status,
        get_availability,
        set_availability,
        record_attestation,
    )
    from provenance_receipt import (
        ProvenanceReceiptGenerator,
        ProvenanceReceipt,
        generate_dummy_attestation,
    )


DB_PATH = "relic_market.db"

DURATION_OPTIONS = [1, 4, 24]  # hours


class ReservationStatus(Enum):
    """Possible states of a reservation."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class Reservation:
    """A machine reservation."""
    reservation_id: str
    session_id: str
    machine_passport_id: str
    renter_agent_id: str
    
    # Time slot
    start_time: float
    duration_hours: int  # 1, 4, or 24
    
    # Payment
    rtc_amount: float  # Total RTC locked in escrow
    escrow_tx_id: str = ""
    payment_status: str = "pending"  # pending, locked, released, refunded
    
    # Access
    ssh_credentials: Dict[str, str] = field(default_factory=dict)
    api_token: str = ""
    
    # Status
    status: str = "pending"
    
    # Receipt
    receipt: Optional[Dict] = None
    
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def init_reservation_db(db_path: str = DB_PATH) -> None:
    """Initialize the reservation database."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relic_reservations (
                reservation_id TEXT PRIMARY KEY,
                session_id TEXT UNIQUE NOT NULL,
                machine_passport_id TEXT NOT NULL,
                renter_agent_id TEXT NOT NULL,
                start_time REAL NOT NULL,
                duration_hours INTEGER NOT NULL,
                rtc_amount REAL NOT NULL,
                escrow_tx_id TEXT DEFAULT '',
                payment_status TEXT DEFAULT 'pending',
                ssh_credentials_json TEXT DEFAULT '{}',
                api_token TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                receipt_json TEXT DEFAULT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reservation_machine
            ON relic_reservations(machine_passport_id)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reservation_renter
            ON relic_reservations(renter_agent_id)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reservation_status
            ON relic_reservations(status)
        """)
        
        # Escrow table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relic_escrow (
                escrow_id TEXT PRIMARY KEY,
                reservation_id TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'locked',
                created_at REAL NOT NULL,
                released_at REAL DEFAULT NULL,
                FOREIGN KEY (reservation_id) REFERENCES relic_reservations(reservation_id)
            )
        """)


def _validate_duration(duration_hours: int) -> bool:
    """Validate reservation duration."""
    return duration_hours in DURATION_OPTIONS


def _calculate_cost(machine: Dict, duration_hours: int) -> float:
    """Calculate RTC cost for a reservation."""
    return machine["rental_price_per_hour"] * duration_hours


def _generate_ssh_credentials(machine_passport_id: str, session_id: str) -> Dict[str, str]:
    """Generate SSH credentials for a reservation session."""
    # In production, this would provision actual SSH access
    return {
        "host": f"relic-{machine_passport_id.lower()}.local",
        "port": "2222",
        "user": f"session_{session_id[:8]}",
        "key_fingerprint": hashlib.sha256(
            f"{machine_passport_id}:{session_id}".encode()
        ).hexdigest()[:16],
    }


def create_reservation(
    machine_passport_id: str,
    renter_agent_id: str,
    start_time: float,
    duration_hours: int,
    rtc_payment_tx: str = "",
    db_path: str = DB_PATH,
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Create a new machine reservation.
    
    Returns:
        Tuple of (success, message, reservation_dict or None)
    """
    # Validate machine exists
    machine = get_machine(machine_passport_id, db_path)
    if not machine:
        return False, f"Machine {machine_passport_id} not found", None
    
    # Validate duration
    if not _validate_duration(duration_hours):
        return False, f"Invalid duration. Must be one of {DURATION_OPTIONS}", None
    
    # Check machine availability
    if machine["status"] != "available":
        return False, f"Machine is {machine['status']}", None
    
    # Check time slot availability
    start_date = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d")
    start_hour = datetime.fromtimestamp(start_time).hour
    
    availability = get_availability(machine_passport_id, start_date, db_path)
    if str(start_hour) in availability and not availability[str(start_hour)]:
        return False, f"Time slot {start_hour}:00 is not available", None
    
    # Calculate cost
    cost = _calculate_cost(machine, duration_hours)
    
    # Generate IDs
    reservation_id = hashlib.sha256(
        f"{machine_passport_id}:{renter_agent_id}:{start_time}:{uuid.uuid4().hex}".encode()
    ).hexdigest()[:24]
    
    session_id = f"session_{uuid.uuid4().hex[:16]}"
    
    reservation = Reservation(
        reservation_id=reservation_id,
        session_id=session_id,
        machine_passport_id=machine_passport_id,
        renter_agent_id=renter_agent_id,
        start_time=start_time,
        duration_hours=duration_hours,
        rtc_amount=cost,
        payment_status="locked" if rtc_payment_tx else "pending",
        ssh_credentials=_generate_ssh_credentials(machine_passport_id, session_id),
        status=ReservationStatus.CONFIRMED.value,
    )
    
    # Save to database
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO relic_reservations 
            (reservation_id, session_id, machine_passport_id, renter_agent_id,
             start_time, duration_hours, rtc_amount, escrow_tx_id, payment_status,
             ssh_credentials_json, api_token, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reservation.reservation_id,
            reservation.session_id,
            reservation.machine_passport_id,
            reservation.renter_agent_id,
            reservation.start_time,
            reservation.duration_hours,
            reservation.rtc_amount,
            reservation.escrow_tx_id,
            reservation.payment_status,
            json.dumps(reservation.ssh_credentials),
            reservation.api_token,
            reservation.status,
            reservation.created_at,
            reservation.updated_at,
        ))
        
        # Lock RTC in escrow
        if cost > 0:
            escrow_id = hashlib.sha256(
                f"{reservation_id}:{time.time()}".encode()
            ).hexdigest()[:24]
            
            conn.execute("""
                INSERT INTO relic_escrow 
                (escrow_id, reservation_id, amount, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (escrow_id, reservation_id, cost, "locked", time.time()))
    
    # Mark time slot as unavailable
    end_hour = start_hour + duration_hours
    for h in range(start_hour, min(end_hour, 24)):
        availability[str(h)] = False
    set_availability(machine_passport_id, start_date, availability, db_path)
    
    # Update machine status if reservation starts soon
    if start_time - time.time() < 3600:  # Starting within 1 hour
        update_machine_status(machine_passport_id, "reserved", db_path)
    
    return True, "Reservation created", asdict(reservation)


def confirm_reservation(
    reservation_id: str,
    payment_tx_id: str,
    db_path: str = DB_PATH,
) -> Tuple[bool, str]:
    """Confirm a reservation with payment."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM relic_reservations WHERE reservation_id = ?",
            (reservation_id,)
        ).fetchone()
        
        if not row:
            return False, "Reservation not found"
        
        conn.execute("""
            UPDATE relic_reservations 
            SET payment_status = 'locked', escrow_tx_id = ?, updated_at = ?
            WHERE reservation_id = ?
        """, (payment_tx_id, time.time(), reservation_id))
    
    return True, "Payment confirmed"


def complete_reservation(
    reservation_id: str,
    output_hash: str,
    computation_description: str,
    db_path: str = DB_PATH,
) -> Tuple[bool, str, Optional[Dict]]:
    """
    Complete a reservation and generate provenance receipt.
    
    Args:
        reservation_id: The reservation ID
        output_hash: Hash of the computation output
        computation_description: Description of the computation
    
    Returns:
        Tuple of (success, message, receipt_dict or None)
    """
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM relic_reservations WHERE reservation_id = ?",
            (reservation_id,)
        ).fetchone()
        
        if not row:
            return False, "Reservation not found", None
        
        res = {
            "reservation_id": row[0],
            "session_id": row[1],
            "machine_passport_id": row[2],
            "renter_agent_id": row[3],
            "start_time": row[4],
            "duration_hours": row[5],
            "rtc_amount": row[6],
            "status": row[11],
        }
    
    if res["status"] not in [ReservationStatus.CONFIRMED.value, ReservationStatus.ACTIVE.value]:
        return False, f"Cannot complete reservation in state: {res['status']}", None
    
    # Get machine for signing key
    machine = get_machine(res["machine_passport_id"], db_path)
    
    # Generate attestation
    attestation = generate_dummy_attestation(
        res["machine_passport_id"],
        res["session_id"]
    )
    
    # Generate provenance receipt
    generator = ProvenanceReceiptGenerator(
        private_key_hex=machine.get("ed25519_private_key", "")
    )
    
    receipt = generator.generate_receipt(
        machine_passport_id=res["machine_passport_id"],
        session_id=res["session_id"],
        renter_agent_id=res["renter_agent_id"],
        duration_hours=res["duration_hours"],
        start_time=res["start_time"],
        output_hash=output_hash,
        computation_description=computation_description,
        attestation_proof=attestation,
        rtc_amount_locked=res["rtc_amount"],
    )
    
    # Update reservation status
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            UPDATE relic_reservations 
            SET status = ?, receipt_json = ?, updated_at = ?
            WHERE reservation_id = ?
        """, (
            ReservationStatus.COMPLETED.value,
            json.dumps(receipt.to_dict()),
            time.time(),
            reservation_id,
        ))
        
        # Release escrow to owner
        conn.execute("""
            UPDATE relic_escrow 
            SET status = 'released', released_at = ?
            WHERE reservation_id = ?
        """, (time.time(), reservation_id))
        
        # Make machine available again
        update_machine_status(res["machine_passport_id"], "available", db_path)
    
    # Record attestation
    record_attestation(res["machine_passport_id"], attestation, db_path)
    
    return True, "Reservation completed", receipt.to_dict()


def cancel_reservation(
    reservation_id: str,
    db_path: str = DB_PATH,
) -> Tuple[bool, str]:
    """Cancel a reservation and refund escrow."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM relic_reservations WHERE reservation_id = ?",
            (reservation_id,)
        ).fetchone()
        
        if not row:
            return False, "Reservation not found"
        
        status = row[11]
        if status in [ReservationStatus.COMPLETED.value, ReservationStatus.CANCELLED.value]:
            return False, f"Cannot cancel reservation in state: {status}"
        
        # Refund escrow
        conn.execute("""
            UPDATE relic_escrow 
            SET status = 'refunded', released_at = ?
            WHERE reservation_id = ? AND status = 'locked'
        """, (time.time(), reservation_id))
        
        # Update reservation
        conn.execute("""
            UPDATE relic_reservations 
            SET status = ?, payment_status = 'refunded', updated_at = ?
            WHERE reservation_id = ?
        """, (ReservationStatus.CANCELLED.value, time.time(), reservation_id))
        
        # Free up time slots
        machine_passport_id = row[2]
        start_time = row[4]
        duration_hours = row[5]
        
        start_date = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d")
        start_hour = datetime.fromtimestamp(start_time).hour
        
        availability = get_availability(machine_passport_id, start_date, db_path)
        end_hour = start_hour + duration_hours
        for h in range(start_hour, min(end_hour, 24)):
            availability[str(h)] = True
        set_availability(machine_passport_id, start_date, availability, db_path)
        
        # Make machine available
        update_machine_status(machine_passport_id, "available", db_path)
    
    return True, "Reservation cancelled and refunded"


def get_reservation(reservation_id: str, db_path: str = DB_PATH) -> Optional[Dict]:
    """Get a reservation by ID."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM relic_reservations WHERE reservation_id = ?",
            (reservation_id,)
        ).fetchone()
        
        if not row:
            return None
        
        return {
            "reservation_id": row["reservation_id"],
            "session_id": row["session_id"],
            "machine_passport_id": row["machine_passport_id"],
            "renter_agent_id": row["renter_agent_id"],
            "start_time": row["start_time"],
            "duration_hours": row["duration_hours"],
            "rtc_amount": row["rtc_amount"],
            "escrow_tx_id": row["escrow_tx_id"],
            "payment_status": row["payment_status"],
            "ssh_credentials": json.loads(row["ssh_credentials_json"]),
            "api_token": row["api_token"],
            "status": row["status"],
            "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def get_receipt(receipt_id: str, db_path: str = DB_PATH) -> Optional[Dict]:
    """Get a receipt by ID."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT receipt_json FROM relic_reservations WHERE receipt_json LIKE ?",
            (f"%\"receipt_id\": \"{receipt_id}\"%",)
        ).fetchone()
        
        if row and row["receipt_json"]:
            return json.loads(row["receipt_json"])
        return None


def list_reservations(
    renter_agent_id: Optional[str] = None,
    machine_passport_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: str = DB_PATH,
) -> List[Dict]:
    """List reservations with optional filters."""
    query = "SELECT * FROM relic_reservations WHERE 1=1"
    params = []
    
    if renter_agent_id:
        query += " AND renter_agent_id = ?"
        params.append(renter_agent_id)
    
    if machine_passport_id:
        query += " AND machine_passport_id = ?"
        params.append(machine_passport_id)
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY created_at DESC"
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        
        reservations = []
        for row in rows:
            reservations.append({
                "reservation_id": row["reservation_id"],
                "session_id": row["session_id"],
                "machine_passport_id": row["machine_passport_id"],
                "renter_agent_id": row["renter_agent_id"],
                "start_time": row["start_time"],
                "duration_hours": row["duration_hours"],
                "rtc_amount": row["rtc_amount"],
                "status": row["status"],
                "payment_status": row["payment_status"],
                "created_at": row["created_at"],
            })
        return reservations


def get_machine_leaderboard(db_path: str = DB_PATH) -> List[Dict]:
    """Get the most rented machines (leaderboard)."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT machine_passport_id, COUNT(*) as rental_count,
                   SUM(rtc_amount) as total_revenue
            FROM relic_reservations
            WHERE status = 'completed'
            GROUP BY machine_passport_id
            ORDER BY rental_count DESC
            LIMIT 20
        """).fetchall()
        
        leaderboard = []
        for row in rows:
            machine = get_machine(row["machine_passport_id"], db_path)
            leaderboard.append({
                "rank": len(leaderboard) + 1,
                "passport_id": row["machine_passport_id"],
                "nickname": machine["nickname"] if machine else "Unknown",
                "model": machine["specs"]["model"] if machine else "Unknown",
                "rental_count": row["rental_count"],
                "total_revenue": row["total_revenue"] or 0,
            })
        
        return leaderboard


if __name__ == "__main__":
    from .machine_registry import init_registry_db, seed_demo_machines, list_machines
    
    init_registry_db()
    init_reservation_db()
    seed_demo_machines()
    
    machines = list_machines()
    if machines:
        machine = machines[0]
        success, msg, res = create_reservation(
            machine_passport_id=machine["passport_id"],
            renter_agent_id="agent_demo_requester",
            start_time=time.time() + 86400,  # Tomorrow
            duration_hours=4,
        )
        print(f"Reservation: {success}, {msg}")
        if res:
            print(f"Reservation ID: {res['reservation_id']}")
            print(f"Session ID: {res['session_id']}")
            print(f"Cost: {res['rtc_amount']} RTC")
