"""
Provenance Receipt Generator for Rent-a-Relic Market
Generates cryptographically signed receipts for machine reservations.
"""

import json
import hashlib
import hmac
import time
import base64
from typing import Dict, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

try:
    import nacl.signing
    import nacl.encoding
    NACL_AVAILABLE = True
except ImportError:
    NACL_AVAILABLE = False


@dataclass
class ProvenanceReceipt:
    """A signed provenance receipt for a machine reservation session."""
    receipt_id: str
    machine_passport_id: str
    session_id: str
    renter_agent_id: str
    
    # Session details
    duration_hours: int  # 1, 4, or 24
    start_time: float
    end_time: float
    
    # Computation details
    output_hash: str  # Hash of computation output
    computation_description: str
    
    # Hardware attestation
    attestation_proof: Dict[str, Any]
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    rtc_amount_locked: float = 0.0
    receipt_signature: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "receipt_id": self.receipt_id,
            "machine_passport_id": self.machine_passport_id,
            "session_id": self.session_id,
            "renter_agent_id": self.renter_agent_id,
            "duration_hours": self.duration_hours,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "output_hash": self.output_hash,
            "computation_description": self.computation_description,
            "attestation_proof": self.attestation_proof,
            "created_at": self.created_at,
            "rtc_amount_locked": self.rtc_amount_locked,
            "receipt_signature": self.receipt_signature,
        }
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def verify_signature(self, public_key_hex: str) -> bool:
        """Verify the receipt signature using the machine's public key."""
        if not self.receipt_signature:
            return False
        
        if NACL_AVAILABLE:
            try:
                public_key_bytes = bytes.fromhex(public_key_hex)
                signature_bytes = bytes.fromhex(self.receipt_signature)
                message = self._signature_message()
                
                verify_key = nacl.signing.VerifyKey(public_key_bytes)
                verify_key.verify(message.encode(), signature_bytes)
                return True
            except Exception:
                return False
        else:
            # Fallback: HMAC verification
            return hmac.verify(
                public_key_hex.encode(),
                signature_bytes,
                self._signature_message().encode()
            ) is None


class ProvenanceReceiptGenerator:
    """Generates and signs provenance receipts."""
    
    def __init__(self, private_key_hex: Optional[str] = None):
        """
        Initialize with machine's Ed25519 private key.
        
        Args:
            private_key_hex: Hex-encoded Ed25519 private key (32 bytes)
        """
        self.private_key_hex = private_key_hex
        
        if NACL_AVAILABLE and private_key_hex:
            self.signing_key = nacl.signing.SigningKey(
                bytes.fromhex(private_key_hex)
            )
        else:
            self.signing_key = None
    
    def _signature_message(self) -> str:
        """Create the canonical message to be signed."""
        return json.dumps({
            "receipt_id": self.receipt_id,
            "machine_passport_id": self.machine_passport_id,
            "session_id": self.session_id,
            "duration_hours": self.duration_hours,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "output_hash": self.output_hash,
            "created_at": self.created_at,
        }, sort_keys=True)
    
    def generate_receipt(
        self,
        machine_passport_id: str,
        session_id: str,
        renter_agent_id: str,
        duration_hours: int,
        start_time: float,
        output_hash: str,
        computation_description: str,
        attestation_proof: Dict[str, Any],
        rtc_amount_locked: float,
    ) -> ProvenanceReceipt:
        """Generate a new provenance receipt."""
        # Calculate end time
        end_time = start_time + (duration_hours * 3600)
        
        # Generate receipt ID
        receipt_content = f"{machine_passport_id}:{session_id}:{output_hash}:{time.time()}"
        receipt_id = hashlib.sha256(receipt_content.encode()).hexdigest()[:24]
        
        receipt = ProvenanceReceipt(
            receipt_id=receipt_id,
            machine_passport_id=machine_passport_id,
            session_id=session_id,
            renter_agent_id=renter_agent_id,
            duration_hours=duration_hours,
            start_time=start_time,
            end_time=end_time,
            output_hash=output_hash,
            computation_description=computation_description,
            attestation_proof=attestation_proof,
            created_at=time.time(),
            rtc_amount_locked=rtc_amount_locked,
        )
        
        # Sign the receipt
        receipt.receipt_signature = self._sign_receipt(receipt)
        
        return receipt
    
    def _sign_receipt(self, receipt: ProvenanceReceipt) -> str:
        """Sign the receipt with the machine's Ed25519 key."""
        message = json.dumps({
            "receipt_id": receipt.receipt_id,
            "machine_passport_id": receipt.machine_passport_id,
            "session_id": receipt.session_id,
            "duration_hours": receipt.duration_hours,
            "start_time": receipt.start_time,
            "end_time": receipt.end_time,
            "output_hash": receipt.output_hash,
            "created_at": receipt.created_at,
        }, sort_keys=True)
        
        if self.signing_key:
            try:
                signed = self.signing_key.sign(message.encode())
                return signed.signature.hex()
            except Exception:
                return self._hmac_fallback_sign(message)
        else:
            return self._hmac_fallback_sign(message)
    
    def _hmac_fallback_sign(self, message: str) -> str:
        """Fallback HMAC signing when NaCl is not available."""
        if self.private_key_hex:
            key = self.private_key_hex.encode()
        else:
            key = b"relic_market_default_key_fallback"
        
        signature = hmac.new(key, message.encode(), hashlib.sha256).digest()
        return signature.hex()


@dataclass
class AttestationProof:
    """Hardware attestation proof for a session."""
    machine_fingerprint: str
    session_challenge: str
    session_response: str
    hardware_signature: str
    rom_checksum: str
    cpu_id: str
    timestamp: float
    epoch_number: int
    
    def to_dict(self) -> Dict:
        return asdict(self)


def generate_dummy_attestation(
    machine_passport_id: str,
    session_id: str,
) -> Dict[str, Any]:
    """Generate a dummy attestation proof for demo purposes."""
    challenge = hashlib.sha256(
        f"{machine_passport_id}:{session_id}:{time.time()}".encode()
    ).hexdigest()
    
    response = hashlib.sha256(
        f"{challenge}:{machine_passport_id}".encode()
    ).hexdigest()
    
    return {
        "machine_fingerprint": machine_passport_id,
        "session_challenge": challenge[:16],
        "session_response": response[:16],
        "hardware_signature": hashlib.sha256(
            f"{machine_passport_id}:{response}".encode()
        ).hexdigest()[:32],
        "rom_checksum": hashlib.sha256(b"ROM_v1.0").hexdigest()[:8],
        "cpu_id": f"CPU_{machine_passport_id[:8]}",
        "timestamp": time.time(),
        "epoch_number": int(time.time() // 300),  # 5-minute epochs
    }


# Standalone verification (for receipt verification without the generator)
def verify_receipt(receipt: Dict, public_key_hex: str) -> bool:
    """Verify a receipt's signature."""
    if not receipt.get("receipt_signature"):
        return False
    
    message = json.dumps({
        "receipt_id": receipt["receipt_id"],
        "machine_passport_id": receipt["machine_passport_id"],
        "session_id": receipt["session_id"],
        "duration_hours": receipt["duration_hours"],
        "start_time": receipt["start_time"],
        "end_time": receipt["end_time"],
        "output_hash": receipt["output_hash"],
        "created_at": receipt["created_at"],
    }, sort_keys=True)
    
    if NACL_AVAILABLE:
        try:
            verify_key = nacl.signing.VerifyKey(bytes.fromhex(public_key_hex))
            verify_key.verify(message.encode(), bytes.fromhex(receipt["receipt_signature"]))
            return True
        except Exception:
            return False
    else:
        expected_sig = hmac.new(
            public_key_hex.encode(),
            message.encode(),
            hashlib.sha256
        ).digest().hex()
        return hmac.compare_digest(expected_sig, receipt["receipt_signature"])


if __name__ == "__main__":
    # Demo usage
    generator = ProvenanceReceiptGenerator()
    
    proof = generate_dummy_attestation("MACHINE001", "session_123")
    
    receipt = generator.generate_receipt(
        machine_passport_id="MACHINE001",
        session_id="session_123",
        renter_agent_id="agent_demo_001",
        duration_hours=4,
        start_time=time.time(),
        output_hash=hashlib.sha256(b"computation_output").hexdigest(),
        computation_description="Retro gaming benchmark run",
        attestation_proof=proof,
        rtc_amount_locked=4.8,
    )
    
    print("Generated Receipt:")
    print(receipt.to_json())
    print(f"\nReceipt ID: {receipt.receipt_id}")
    print(f"Signature: {receipt.receipt_signature[:32]}...")
