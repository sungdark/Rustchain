#!/usr/bin/env python3
"""
Rent-a-Relic Market Flask Server
Mounts the relic market API and serves the web UI.

Run: python relic_market_server.py
API runs on http://localhost:5001 by default
"""

import os
import sys
import logging

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from flask import Flask, send_from_directory, jsonify
from relic_market.machine_registry import init_registry_db, seed_demo_machines, list_machines
from relic_market.reservation_system import init_reservation_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("relic_market")


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    
    # Import and register blueprint
    from relic_market.relic_market_api import relic_api
    app.register_blueprint(relic_api, url_prefix='/api')
    
    # Serve web UI
    web_dir = os.path.join(os.path.dirname(__file__), '..', 'web', 'relic-market')
    
    @app.route('/')
    def index():
        return send_from_directory(web_dir, 'index.html')
    
    @app.route('/relic-market/<path:filename>')
    def serve_static(filename):
        return send_from_directory(web_dir, filename)
    
    # Initialize databases (called directly since before_first_request is deprecated)
    log.info("Initializing databases...")
    try:
        init_registry_db()
        init_reservation_db()
        
        # Seed demo machines if empty
        machines = list_machines()
        if len(machines) == 0:
            log.info("Seeding demo machines...")
            seed_demo_machines()
            log.info(f"Seeded {len(list_machines())} machines")
        else:
            log.info(f"Found {len(machines)} existing machines")
    except Exception as e:
        log.error(f"Database init error: {e}")
    
    return app


def main():
    """Main entry point."""
    app = create_app()
    port = int(os.environ.get('PORT', 5001))
    log.info(f"Starting Rent-a-Relic Market API on port {port}")
    log.info(f"Web UI: http://localhost:{port}/")
    log.info(f"API Base: http://localhost:{port}/api")
    app.run(host='0.0.0.0', port=port, debug=False)


if __name__ == '__main__':
    main()
