"""
Machine Registry for Rent-a-Relic Market
Lists available vintage machines with specs, photos, runtime, and attestation history.
"""

import json
import sqlite3
import hashlib
import time
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict, field
from pathlib import Path

DB_PATH = "relic_market.db"


@dataclass
class MachineSpecs:
    """Hardware specifications of a vintage machine."""
    arch: str  # e.g., "MOS 6502", "Motorola 68000", "Z80", "PowerPC"
    model: str  # e.g., "Commodore 64", "Apple Macintosh II", "IBM PC/AT"
    manufacturer: str
    manufacture_year: int
    cpu_clock_mhz: float
    ram_kb: int
    storage: str  # e.g., "5.25\" Floppy", "40MB HDD"
    display: str  # e.g., "CRT Composite", "Amber Monochrome"
    ports: str  # e.g., "RS-232, Parallel, Cartridge"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Machine:
    """A vintage machine in the registry."""
    passport_id: str  # Unique identifier (fingerprint hash)
    nickname: str
    specs: MachineSpecs
    photos: List[str]  # URLs or paths to photos
    uptime_hours: int
    attestation_count: int
    attestation_history: List[Dict] = field(default_factory=list)
    ed25519_public_key: str = ""
    ed25519_private_key: str = ""  # Only stored locally, never exposed
    ssh_access_enabled: bool = True
    api_endpoint: str = ""
    status: str = "available"  # available, reserved, maintenance, offline
    rental_price_per_hour: float = 1.0  # RTC
    owner_agent_id: str = ""
    created_at: float = field(default_factory=time.time)
    last_attestation: float = 0
    
    def to_dict(self) -> Dict:
        return {
            "passport_id": self.passport_id,
            "nickname": self.nickname,
            "specs": self.specs.to_dict(),
            "photos": self.photos,
            "uptime_hours": self.uptime_hours,
            "attestation_count": self.attestation_count,
            "attestation_history": self.attestation_history,
            "ed25519_public_key": self.ed25519_public_key,
            "ssh_access_enabled": self.ssh_access_enabled,
            "api_endpoint": self.api_endpoint,
            "status": self.status,
            "rental_price_per_hour": self.rental_price_per_hour,
            "owner_agent_id": self.owner_agent_id,
            "created_at": self.created_at,
            "last_attestation": self.last_attestation,
        }


def init_registry_db(db_path: str = DB_PATH) -> None:
    """Initialize the machine registry database."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS relic_machines (
                passport_id TEXT PRIMARY KEY,
                nickname TEXT NOT NULL,
                specs_json TEXT NOT NULL,
                photos_json TEXT NOT NULL,
                uptime_hours INTEGER DEFAULT 0,
                attestation_count INTEGER DEFAULT 0,
                attestation_history_json TEXT DEFAULT '[]',
                ed25519_public_key TEXT DEFAULT '',
                ed25519_private_key TEXT DEFAULT '',
                ssh_access_enabled INTEGER DEFAULT 1,
                api_endpoint TEXT DEFAULT '',
                status TEXT DEFAULT 'available',
                rental_price_per_hour REAL DEFAULT 1.0,
                owner_agent_id TEXT DEFAULT '',
                created_at REAL NOT NULL,
                last_attestation REAL DEFAULT 0
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS machine_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                passport_id TEXT NOT NULL,
                date TEXT NOT NULL,
                hour_slots_json TEXT NOT NULL,
                FOREIGN KEY (passport_id) REFERENCES relic_machines(passport_id)
            )
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_availability_passport 
            ON machine_availability(passport_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_availability_date 
            ON machine_availability(date)
        """)


def generate_passport_id(machine_data: Dict) -> str:
    """Generate a unique passport ID from machine data."""
    content = json.dumps(machine_data, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16].upper()


def register_machine(machine: Machine, db_path: str = DB_PATH) -> bool:
    """Register a new machine in the registry."""
    machine.passport_id = generate_passport_id({
        "model": machine.specs.model,
        "manufacturer": machine.specs.manufacturer,
        "year": machine.specs.manufacture_year,
        "arch": machine.specs.arch,
    })
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO relic_machines 
            (passport_id, nickname, specs_json, photos_json, uptime_hours,
             attestation_count, attestation_history_json, ed25519_public_key,
             ed25519_private_key, ssh_access_enabled, api_endpoint, status,
             rental_price_per_hour, owner_agent_id, created_at, last_attestation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            machine.passport_id,
            machine.nickname,
            json.dumps(machine.specs.to_dict()),
            json.dumps(machine.photos),
            machine.uptime_hours,
            machine.attestation_count,
            json.dumps(machine.attestation_history),
            machine.ed25519_public_key,
            machine.ed25519_private_key,
            int(machine.ssh_access_enabled),
            machine.api_endpoint,
            machine.status,
            machine.rental_price_per_hour,
            machine.owner_agent_id,
            machine.created_at,
            machine.last_attestation,
        ))
    return True


def get_machine(passport_id: str, db_path: str = DB_PATH) -> Optional[Dict]:
    """Get machine details by passport ID."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM relic_machines WHERE passport_id = ?",
            (passport_id,)
        ).fetchone()
        
        if not row:
            return None
        
        return {
            "passport_id": row["passport_id"],
            "nickname": row["nickname"],
            "specs": json.loads(row["specs_json"]),
            "photos": json.loads(row["photos_json"]),
            "uptime_hours": row["uptime_hours"],
            "attestation_count": row["attestation_count"],
            "attestation_history": json.loads(row["attestation_history_json"]),
            "ed25519_public_key": row["ed25519_public_key"],
            "ssh_access_enabled": bool(row["ssh_access_enabled"]),
            "api_endpoint": row["api_endpoint"],
            "status": row["status"],
            "rental_price_per_hour": row["rental_price_per_hour"],
            "owner_agent_id": row["owner_agent_id"],
            "created_at": row["created_at"],
            "last_attestation": row["last_attestation"],
        }


def list_machines(
    status: Optional[str] = None,
    arch: Optional[str] = None,
    min_uptime: int = 0,
    db_path: str = DB_PATH
) -> List[Dict]:
    """List all machines with optional filters."""
    query = "SELECT * FROM relic_machines WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    if arch:
        query += " AND specs_json LIKE ?"
        params.append(f"%\"arch\": \"{arch}%\"")
    
    if min_uptime > 0:
        query += " AND uptime_hours >= ?"
        params.append(min_uptime)
    
    query += " ORDER BY attestation_count DESC"
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        
        machines = []
        for row in rows:
            machines.append({
                "passport_id": row["passport_id"],
                "nickname": row["nickname"],
                "specs": json.loads(row["specs_json"]),
                "photos": json.loads(row["photos_json"]),
                "uptime_hours": row["uptime_hours"],
                "attestation_count": row["attestation_count"],
                "status": row["status"],
                "rental_price_per_hour": row["rental_price_per_hour"],
                "ssh_access_enabled": bool(row["ssh_access_enabled"]),
            })
        return machines


def update_machine_status(passport_id: str, status: str, db_path: str = DB_PATH) -> bool:
    """Update machine status."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE relic_machines SET status = ? WHERE passport_id = ?",
            (status, passport_id)
        )
    return True


def get_availability(passport_id: str, date: str, db_path: str = DB_PATH) -> Dict:
    """Get machine availability for a specific date.
    
    Args:
        passport_id: Machine passport ID
        date: Date in YYYY-MM-DD format
    
    Returns:
        Dict with hour slots (0-23), each indicating if available
    """
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT hour_slots_json FROM machine_availability WHERE passport_id = ? AND date = ?",
            (passport_id, date)
        ).fetchone()
        
        if row:
            return json.loads(row["hour_slots_json"])
        
        # Default: all slots available
        return {str(h): True for h in range(24)}


def set_availability(
    passport_id: str,
    date: str,
    slots: Dict[str, bool],
    db_path: str = DB_PATH
) -> None:
    """Set machine availability for a date."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO machine_availability (passport_id, date, hour_slots_json)
            VALUES (?, ?, ?)
        """, (passport_id, date, json.dumps(slots)))


def record_attestation(
    passport_id: str,
    attestation_data: Dict,
    db_path: str = DB_PATH
) -> None:
    """Record a new attestation for a machine."""
    attestation_data["timestamp"] = time.time()
    
    with sqlite3.connect(db_path) as conn:
        # Get current history
        row = conn.execute(
            "SELECT attestation_history_json, attestation_count FROM relic_machines WHERE passport_id = ?",
            (passport_id,)
        ).fetchone()
        
        if row:
            history = json.loads(row["attestation_history_json"])
            history.append(attestation_data)
            count = row["attestation_count"] + 1
        else:
            history = [attestation_data]
            count = 1
        
        conn.execute("""
            UPDATE relic_machines 
            SET attestation_history_json = ?, attestation_count = ?, last_attestation = ?
            WHERE passport_id = ?
        """, (json.dumps(history), count, time.time(), passport_id))


def seed_demo_machines(db_path: str = DB_PATH) -> None:
    """Seed the database with demo vintage machines."""
    demo_machines = [
        Machine(
            passport_id="",
            nickname="Silver Surfer",
            specs=MachineSpecs(
                arch="MOS 6502",
                model="Commodore 64",
                manufacturer="Commodore",
                manufacture_year=1982,
                cpu_clock_mhz=1.0,
                ram_kb=64,
                storage="1541 Floppy Drive",
                display="CRT Composite",
                ports="Cartridge, Serial, User Port",
            ),
            photos=["https://placeholder.relic.market/c64.jpg"],
            uptime_hours=12847,
            attestation_count=342,
            ed25519_public_key="DEMO_KEY_C64_001",
            ssh_access_enabled=True,
            api_endpoint="ssh://relic-c64.local:2222",
            status="available",
            rental_price_per_hour=0.5,
            owner_agent_id="agent_silver_surfer",
        ),
        Machine(
            passport_id="",
            nickname="Mac Daddy",
            specs=MachineSpecs(
                arch="Motorola 68000",
                model="Apple Macintosh II",
                manufacturer="Apple",
                manufacture_year=1987,
                cpu_clock_mhz=16.0,
                ram_kb=4096,
                storage="40MB SCSI HDD",
                display="CRT 512x384",
                ports="ADB, SCSI, Serial, NuBus",
            ),
            photos=["https://placeholder.relic.market/macii.jpg"],
            uptime_hours=8921,
            attestation_count=187,
            ed25519_public_key="DEMO_KEY_MACII_001",
            ssh_access_enabled=True,
            api_endpoint="ssh://relic-macii.local:2222",
            status="available",
            rental_price_per_hour=1.2,
            owner_agent_id="agent_mac_daddy",
        ),
        Machine(
            passport_id="",
            nickname="Big Blue Box",
            specs=MachineSpecs(
                arch="Intel 80286",
                model="IBM PC/AT",
                manufacturer="IBM",
                manufacture_year=1984,
                cpu_clock_mhz=6.0,
                ram_kb=512,
                storage="30MB MFM HDD",
                display="CGA",
                ports="Serial, Parallel, AT Keyboard",
            ),
            photos=["https://placeholder.relic.market/ibmat.jpg"],
            uptime_hours=15632,
            attestation_count=421,
            ed25519_public_key="DEMO_KEY_IBMAT_001",
            ssh_access_enabled=True,
            api_endpoint="ssh://relic-ibmat.local:2222",
            status="available",
            rental_price_per_hour=0.8,
            owner_agent_id="agent_big_blue",
        ),
        Machine(
            passport_id="",
            nickname="Zeppelin",
            specs=MachineSpecs(
                arch="Zilog Z80",
                model="ZX Spectrum 48K",
                manufacturer="Sinclair Research",
                manufacture_year=1982,
                cpu_clock_mhz=3.5,
                ram_kb=48,
                storage="Tape Recorder",
                display="CRT Composite",
                ports="EAR, MIC, Expansion",
            ),
            photos=["https://placeholder.relic.market/zx48k.jpg"],
            uptime_hours=9843,
            attestation_count=256,
            ed25519_public_key="DEMO_KEY_ZX_001",
            ssh_access_enabled=False,
            api_endpoint="",
            status="reserved",
            rental_price_per_hour=0.3,
            owner_agent_id="agent_zeppelin",
        ),
        Machine(
            passport_id="",
            nickname="Warthog",
            specs=MachineSpecs(
                arch="PowerPC 601",
                model="IBM RS/6000 7025",
                manufacturer="IBM",
                manufacture_year=1994,
                cpu_clock_mhz=80.0,
                ram_kb=65536,
                storage="1GB SCSI HDD",
                display="GXT500 Graphics",
                ports="SCSI, Serial, Parallel, MCA",
            ),
            photos=["https://placeholder.relic.market/warthog.jpg"],
            uptime_hours=24653,
            attestation_count=892,
            ed25519_public_key="DEMO_KEY_WARTHOG_001",
            ssh_access_enabled=True,
            api_endpoint="ssh://relic-warthog.local:2222",
            status="available",
            rental_price_per_hour=2.0,
            owner_agent_id="agent_warthog",
        ),
    ]
    
    for machine in demo_machines:
        register_machine(machine, db_path)


if __name__ == "__main__":
    init_registry_db()
    seed_demo_machines()
    print("Machine registry initialized with demo machines.")
    machines = list_machines()
    print(f"Registered machines: {len(machines)}")
    for m in machines:
        print(f"  - {m['passport_id']}: {m['nickname']} ({m['specs']['model']})")
