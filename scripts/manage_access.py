"""Offline provisioning; passwords never appear in command arguments or source."""

import argparse
from getpass import getpass

from backend.access import AccessStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup", help="Interactive first-run setup; never changes an existing instance")
    init = sub.add_parser("init")
    init.add_argument("--organization", required=True)
    user = sub.add_parser("user")
    user.add_argument("username")
    user.add_argument("--role", required=True, choices=["viewer", "operator", "admin"])
    disable = sub.add_parser("disable")
    disable.add_argument("username")
    args = parser.parse_args()
    store = AccessStore()
    if args.command == "setup":
        with store.connect() as db:
            exists = db.execute("SELECT 1 FROM instance_identity").fetchone()
            admin = db.execute("SELECT 1 FROM access_users WHERE enabled=1 AND role='admin'").fetchone()
        if exists and admin:
            store.check_binding()
            print("Existing organization and administrator preserved.")
            return
        if not exists:
            store.provision(input("Organization name (one organization per instance): ").strip())
        username = input("Administrator account name: ").strip()
        password = getpass("New password (12–256 characters): ")
        if password != getpass("Repeat password: "):
            raise SystemExit("Passwords do not match.")
        store.set_user(username, password, "admin")
        print("Administrator created. Sign in with this account in the website.")
    elif args.command == "init":
        store.provision(args.organization)
        print("Organization instance provisioned. Create an admin with the user command.")
    elif args.command == "user":
        password = getpass("New password (12–256 characters): ")
        if password != getpass("Repeat password: "):
            raise SystemExit("Passwords do not match.")
        store.set_user(args.username, password, args.role)
        print("Account saved; previous sessions revoked.")
    else:
        store.disable_user(args.username)
        print("Account disabled and sessions revoked.")


if __name__ == "__main__":
    main()
