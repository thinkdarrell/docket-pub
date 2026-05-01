"""CLI to create an admin user.

Usage:
    python -m docket.web.create_admin <username> <password>
"""

from __future__ import annotations

import argparse
import sys

from werkzeug.security import generate_password_hash

from docket.db import db


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an admin user")
    parser.add_argument("username", help="Admin username")
    parser.add_argument("password", help="Admin password")
    args = parser.parse_args()

    if len(args.password) < 8:
        print("Error: password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    password_hash = generate_password_hash(args.password)

    with db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_users (username, password_hash)
                VALUES (%s, %s)
                ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
                """,
                (args.username, password_hash),
            )
        conn.commit()

    print(f"Admin user '{args.username}' created (or password updated).")


if __name__ == "__main__":
    main()
