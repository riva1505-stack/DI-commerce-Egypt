"""Tenant-scoped manager authentication helpers."""
import hashlib
import hmac
import secrets
import time

SESSION_SECONDS = 28800
