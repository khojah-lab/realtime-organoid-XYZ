"""
routes/__init__.py
────────────────────────────────────────────────────────────────
Registers all Flask route blueprints on the application instance.
────────────────────────────────────────────────────────────────
"""

from flask import Flask
from routes.main_routes import main_bp
from routes.motion_routes import motion_bp
from routes.analysis_routes import analysis_bp


def register_routes(app: Flask) -> None:
    """Register main, motion, and analysis blueprints on the Flask app."""
    app.register_blueprint(main_bp)
    app.register_blueprint(motion_bp)
    app.register_blueprint(analysis_bp)
