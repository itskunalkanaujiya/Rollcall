"""Consistent online backup of the SQLite database (safe while the server is running, WAL-aware).

    python scripts/backup_db.py                      -> backups/attendance-YYYYmmdd-HHMMSS.db
    python scripts/backup_db.py --keep 14            -> also delete all but the 14 newest backups
Restore: stop the backend, then copy a backup over backend/data/attendance.db (see README).
The backup contains ENCRYPTED face templates; keep EMBEDDING_ENCRYPTION_KEY (in backend/.env) separately and safely.
"""
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "backend" / "data" / "attendance.db")
    ap.add_argument("--out", type=Path, default=ROOT / "backups")
    ap.add_argument("--keep", type=int, default=0, help="keep only the N newest backups (0 = keep all)")
    a = ap.parse_args()
    if not a.db.exists():
        print(f"Database not found: {a.db}")
        return 1
    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / f"attendance-{datetime.now():%Y%m%d-%H%M%S}.db"
    src, dst = sqlite3.connect(a.db), sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    ok = sqlite3.connect(dest).execute("PRAGMA integrity_check").fetchone()[0]
    print(f"Backup written: {dest}  (integrity: {ok})")
    if a.keep > 0:
        for old in sorted(a.out.glob("attendance-*.db"))[:-a.keep]:
            old.unlink()
    return 0 if ok == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
