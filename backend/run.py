"""WSGI entry for gunicorn + Flask-SocketIO (eventlet worker)."""
from app import create_app

app = create_app()
