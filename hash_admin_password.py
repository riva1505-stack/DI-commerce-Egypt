"""Generate ADMIN_PASSWORD_HASH without putting a password in shell history."""
from getpass import getpass

from auth_security import hash_password


if __name__ == "__main__":
    password = getpass("Admin password (at least 12 characters): ")
    if len(password.strip()) < 12 or password != getpass("Confirm password: "):
        raise SystemExit("Passwords must match and contain at least 12 non-padding characters.")
    print("ADMIN_PASSWORD_HASH=" + hash_password(password))
