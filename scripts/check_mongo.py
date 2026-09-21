"""Say precisely why MongoDB is or isn't reachable, before blaming the app.

Atlas rejects a non-allowlisted IP by dropping the TLS handshake, which surfaces
as a confusing SSL error rather than "not authorised". This separates the layers
so you know which one to fix.

    python scripts/check_mongo.py
"""
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)


def main() -> int:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print("MONGODB_URI is not set in .env -- the app will use files only.")
        return 1
    host = urlparse(uri).hostname or "?"
    print(f"cluster : {host}")
    print(f"database: {os.environ.get('MONGODB_DB') or 'ladinglens'}")

    try:
        ip = urlopen("https://api.ipify.org", timeout=10).read().decode()
        print(f"your IP : {ip}   <- this is what Atlas must allow")
    except OSError:
        print("your IP : could not determine (Atlas's 'Add Current IP Address' will detect it)")

    try:
        import dns.resolver

        hosts = [str(r.target).rstrip(".") for r in dns.resolver.resolve(f"_mongodb._tcp.{host}", "SRV")]
        print(f"DNS     : OK, {len(hosts)} shard hosts")
    except Exception as exc:                      # noqa: BLE001 - report, don't raise
        print(f"DNS     : FAILED ({type(exc).__name__}) -- check the hostname in MONGODB_URI")
        return 1

    try:
        socket.create_connection((hosts[0], 27017), timeout=10).close()
        print("TCP 27017: open -- the cluster is running")
    except OSError as exc:
        print(f"TCP 27017: blocked ({type(exc).__name__}) -- cluster paused, or a firewall")
        return 1

    from pymongo import MongoClient
    from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=15000)
        version = client.server_info()["version"]
    except ServerSelectionTimeoutError as exc:
        if "TLSV1_ALERT" in str(exc) or "SSL handshake failed" in str(exc):
            print("\nCONNECT : FAILED at the TLS handshake.")
            print("  Atlas drops the handshake for an IP that is not allowlisted, so this")
            print("  almost always means the allowlist -- not your password, which has not")
            print("  even been checked yet.")
            print("  Fix: Atlas > Network Access > Add IP Address.")
            print("  Use 0.0.0.0/0 if Render also needs in; its outbound IPs are not fixed.")
        else:
            print(f"\nCONNECT : FAILED -- {str(exc)[:200]}")
        return 1
    except OperationFailure as exc:
        print(f"\nCONNECT : reached the server, but auth failed -- {exc}")
        print("  The allowlist is fine. Check the username/password in MONGODB_URI.")
        return 1

    print(f"CONNECT : OK -- MongoDB {version}")
    db = client[os.environ.get("MONGODB_DB") or "ladinglens"]
    names = db.list_collection_names()
    print(f"database: readable, collections: {names or 'none yet (created on first run)'}")
    for name in names:
        print(f"  {name}: {db[name].estimated_document_count()} documents")
    print("\nRestart uvicorn, then /api/db/status should show connected: true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
