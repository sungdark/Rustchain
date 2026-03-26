"""
BoTTube Integration for Rent-a-Relic Market
Videos rendered on vintage hardware get a special "Relic Rendered" badge.
"""

import json
import sqlite3
import time
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class BottubeVideo:
    """A BoTTube video with optional relic badge."""
    video_id: str
    title: str
    agent_id: str
    content_url: str
    thumbnail_url: str
    duration_seconds: int
    created_at: float
    render_platform: str = "standard"  # standard, relic
    machine_passport_id: Optional[str] = None
    reservation_id: Optional[str] = None
    relic_badge_applied: bool = False


class RelicBadgeManager:
    """Manages special badges for videos rendered on vintage hardware."""
    
    BADGE_NAME = "Relic Rendered"
    BADGE_COLOR = "#38ff8d"  # Accent green
    BADGE_ICON = "🕹️"
    
    def __init__(self, db_path: str = "relic_market.db"):
        self.db_path = db_path
        self._init_tables()
    
    def _init_tables(self):
        """Initialize badge tracking tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relic_video_badges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE NOT NULL,
                    machine_passport_id TEXT NOT NULL,
                    reservation_id TEXT NOT NULL,
                    session_start REAL NOT NULL,
                    session_end REAL NOT NULL,
                    output_hash TEXT,
                    badge_awarded_at REAL NOT NULL,
                    FOREIGN KEY (machine_passport_id) REFERENCES relic_machines(passport_id),
                    FOREIGN KEY (reservation_id) REFERENCES relic_reservations(reservation_id)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_video_badges_video
                ON relic_video_badges(video_id)
            """)
    
    def award_badge(
        self,
        video_id: str,
        machine_passport_id: str,
        reservation_id: str,
        session_start: float,
        session_end: float,
        output_hash: str = "",
    ) -> Dict[str, Any]:
        """
        Award a "Relic Rendered" badge to a video.
        
        Args:
            video_id: The BoTTube video ID
            machine_passport_id: The machine used for rendering
            reservation_id: The reservation that covered the rendering time
            session_start: Start timestamp of the rendering session
            session_end: End timestamp of the rendering session
            output_hash: Optional hash of the rendered output
        
        Returns:
            Badge data including the badge metadata
        """
        badge_id = hashlib.sha256(
            f"{video_id}:{machine_passport_id}:{time.time()}".encode()
        ).hexdigest()[:16]
        
        badge_data = {
            "badge_id": badge_id,
            "badge_name": self.BADGE_NAME,
            "badge_icon": self.BADGE_ICON,
            "badge_color": self.BADGE_COLOR,
            "machine_passport_id": machine_passport_id,
            "reservation_id": reservation_id,
            "render_platform": "relic",
            "session_duration": session_end - session_start,
            "awarded_at": time.time(),
            "verified": True,
        }
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO relic_video_badges 
                (video_id, machine_passport_id, reservation_id, session_start, session_end, output_hash, badge_awarded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                video_id,
                machine_passport_id,
                reservation_id,
                session_start,
                session_end,
                output_hash,
                time.time(),
            ))
        
        return badge_data
    
    def get_badge(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Get badge data for a video."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM relic_video_badges WHERE video_id = ?",
                (video_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return {
                "badge_id": row["id"],
                "video_id": row["video_id"],
                "machine_passport_id": row["machine_passport_id"],
                "reservation_id": row["reservation_id"],
                "badge_name": self.BADGE_NAME,
                "badge_icon": self.BADGE_ICON,
                "badge_color": self.BADGE_COLOR,
                "render_platform": "relic",
                "session_duration": row["session_end"] - row["session_start"],
                "session_start": row["session_start"],
                "session_end": row["session_end"],
                "awarded_at": row["badge_awarded_at"],
                "verified": True,
            }
    
    def verify_video_badge(self, video_id: str) -> bool:
        """Verify if a video has a valid relic badge."""
        badge = self.get_badge(video_id)
        return badge is not None
    
    def get_machine_render_history(
        self,
        machine_passport_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get all badges awarded for videos rendered on a specific machine."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM relic_video_badges 
                WHERE machine_passport_id = ?
                ORDER BY badge_awarded_at DESC
                LIMIT ?
            """, (machine_passport_id, limit)).fetchall()
            
            return [
                {
                    "video_id": row["video_id"],
                    "reservation_id": row["reservation_id"],
                    "session_duration": row["session_end"] - row["session_start"],
                    "awarded_at": row["badge_awarded_at"],
                }
                for row in rows
            ]


def create_relic_badge_feed(
    videos: List[Dict],
    badge_manager: RelicBadgeManager,
) -> List[Dict]:
    """
    Add relic badge information to a list of videos.
    
    Args:
        videos: List of video dicts from BoTTube
        badge_manager: RelicBadgeManager instance
    
    Returns:
        Videos with badge info added
    """
    for video in videos:
        video_id = video.get("id") or video.get("video_id", "")
        badge = badge_manager.get_badge(video_id)
        
        if badge:
            video["has_relic_badge"] = True
            video["relic_badge"] = {
                "name": badge["badge_name"],
                "icon": badge["badge_icon"],
                "color": badge["badge_color"],
                "machine_passport_id": badge["machine_passport_id"],
                "render_platform": "relic",
            }
        else:
            video["has_relic_badge"] = False
    
    return videos


def inject_relic_badge_to_rss_item(
    item: Dict[str, Any],
    badge_manager: RelicBadgeManager,
) -> Dict[str, Any]:
    """
    Inject relic badge info into an RSS feed item.
    
    Args:
        item: RSS feed item dict
        badge_manager: RelicBadgeManager instance
    
    Returns:
        Item with badge info added
    """
    video_id = item.get("guid", "").split("/")[-1]
    
    if not video_id:
        return item
    
    badge = badge_manager.get_badge(video_id)
    
    if badge:
        # Add badge as a custom element or category
        item["categories"] = item.get("categories", [])
        item["categories"].append(f"🕹️ Relic Rendered on {badge['machine_passport_id']}")
        
        # Add custom namespace element if supported
        item["relic_badge"] = {
            "rendered_on": badge["machine_passport_id"],
            "platform": "relic",
        }
    
    return item


# Example usage with BoTTube RSS feeds:
"""
from bottube_feed import RSSFeedBuilder
from relic_market.bottube_integration import (
    RelicBadgeManager,
    inject_relic_badge_to_rss_item,
)

# Initialize
badge_manager = RelicBadgeManager()

# Build RSS feed with badges
rss = RSSFeedBuilder(title="BoTTube with Relic Badges", link="https://bottube.ai")

# Get videos from BoTTube
videos = get_bottube_videos()

# Add items with badge injection
for video in videos:
    item = create_rss_item(video)
    item = inject_relic_badge_to_rss_item(item, badge_manager)
    rss.add_item(**item)

feed_content = rss.build()
"""


if __name__ == "__main__":
    # Demo
    manager = RelicBadgeManager()
    
    # Award a badge
    badge = manager.award_badge(
        video_id="bottube_video_123",
        machine_passport_id="MACHINE001",
        reservation_id="res_abc123",
        session_start=time.time() - 3600,
        session_end=time.time(),
        output_hash=hashlib.sha256(b"rendered_video").hexdigest(),
    )
    
    print("Awarded badge:", json.dumps(badge, indent=2))
    
    # Check badge
    retrieved = manager.get_badge("bottube_video_123")
    print("Retrieved badge:", retrieved)
    
    # Verify
    print("Is verified:", manager.verify_video_badge("bottube_video_123"))
