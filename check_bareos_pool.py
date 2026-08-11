#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# check_bareos_pool.py - Icinga2 / Nagios plugin for Bareos pool health monitoring
#
# Repository: https://github.com/Nemester/check-bareos-pool
#
# Copyright (C) 2026 Manuel Sonder
#
# This plugin checks the health of a Bareos tape pool via the PostgreSQL
# catalog. It monitors total volume count and the number of volumes that
# are overdue for recycling back to the scratch pool but have not been
# processed yet, which indicates a broken or misconfigured recycle automechanism.
#
# SPDX-License-Identifier: MIT
#
# Changelog
# 2026-05-20   V1.0    Initial implementation

import argparse
import sys
from datetime import datetime, timezone
 
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print(
        "[UNKNOWN] Required Python module 'psycopg2' is not installed.\n"
        "Install it with one of:\n"
        "  pip install psycopg2-binary\n"
        "  apt install python3-psycopg2\n"
        "  yum install python3-psycopg2"
    )
    sys.exit(3)
 
 
VERSION = "1.0"
 
OK = 0
WARNING = 1
CRITICAL = 2
UNKNOWN = 3
 
# VolStatus values that are candidates for recycling back to scratch.
# Bareos should automatically recycle these once their retention expires.
RECYCLABLE_STATUSES = {"Full", "Used"}
 
# Default thresholds — all disabled by default, must be explicitly set
DEFAULT_WARNING_MIN_TOTAL_VOLUMES  = None   # warn if total drops below this
DEFAULT_CRITICAL_MIN_TOTAL_VOLUMES = None   # critical if total drops below this
DEFAULT_WARNING_MAX_TOTAL_VOLUMES  = None   # warn if total rises above this
DEFAULT_CRITICAL_MAX_TOTAL_VOLUMES = None   # critical if total rises above this
 
DEFAULT_WARNING_OVERDUE            = None   # warn if this many volumes are overdue
DEFAULT_CRITICAL_OVERDUE           = None   # critical if this many are overdue
 
 
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
 
def read_password_from_file(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if "Password" in line:
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2].strip('"')
    raise ValueError(f"No password found in {path}")
 
 
def plugin_exit(code: int, message: str, perfdata: str = "") -> None:
    if perfdata:
        print(f"{message} | {perfdata}")
    else:
        print(message)
    sys.exit(code)
 
 
def status_label(code: int) -> str:
    return {
        OK:       "OK",
        WARNING:  "WARNING",
        CRITICAL: "CRITICAL",
        UNKNOWN:  "UNKNOWN",
    }.get(code, "UNKNOWN")
 
 
def connect_db(args):
    try:
        conn = psycopg2.connect(
            host=args.host,
            port=args.port,
            dbname=args.database,
            user=args.user,
            password=args.password,
        )
        return conn
    except Exception as exc:
        plugin_exit(UNKNOWN, f"[UNKNOWN] Database connection failed: {exc}")
 
 
def apply_min_thresholds(value: int, warning_min, critical_min) -> int:
    """Return state when alerting if value drops BELOW a threshold."""
    if critical_min is not None and value <= critical_min:
        return CRITICAL
    if warning_min is not None and value <= warning_min:
        return WARNING
    return OK
 
 
def apply_max_thresholds(value: int, warning_max, critical_max) -> int:
    """Return state when alerting if value rises ABOVE a threshold."""
    if critical_max is not None and value >= critical_max:
        return CRITICAL
    if warning_max is not None and value >= warning_max:
        return WARNING
    return OK
 
 
def combine_codes(*codes: int) -> int:
    return max(codes) if codes else OK
 
 
# ---------------------------------------------------------------------------
# Argument parsing & validation
# ---------------------------------------------------------------------------
 
def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Icinga/Nagios plugin for checking Bareos pool health: "
            "total volume count and overdue-for-recycling volumes"
        )
    )
 
    # Connection
    parser.add_argument("-H", "--host",     default="127.0.0.1", help="PostgreSQL host (default: 127.0.0.1)")
    parser.add_argument("-P", "--port",     type=int, default=5432, help="PostgreSQL port (default: 5432)")
    parser.add_argument("-d", "--database", default="bareos",    help="Database name (default: bareos)")
    parser.add_argument("-U", "--user",     required=True,       help="Database user")
 
    pw_group = parser.add_mutually_exclusive_group()
    pw_group.add_argument("-p", "--password", help="Database password")
    pw_group.add_argument(
        "--password-file",
        default="/etc/bareos/bareos-dir.conf",
        help="File containing 'Password = ...' (default: /etc/bareos/bareos-dir.conf)",
    )
 
    # Pool selection
    parser.add_argument(
        "--pool",
        required=True,
        help="Pool name to check (exact match)",
    )
 
    # Optional filters
    parser.add_argument(
        "--mediatype",
        default=None,
        help="Restrict check to volumes of this media type (e.g. LTO-9)",
    )
    parser.add_argument(
        "--storage",
        default=None,
        help="Restrict check to volumes last used by this storage daemon name (e.g. sd-library1)",
    )
 
    # Total volume count — minimum thresholds (alert when too FEW)
    parser.add_argument(
        "--warning-total-volumes",
        type=int,
        default=DEFAULT_WARNING_MIN_TOTAL_VOLUMES,
        help="WARNING if total volume count <= this value (default: disabled)",
    )
    parser.add_argument(
        "--critical-total-volumes",
        type=int,
        default=DEFAULT_CRITICAL_MIN_TOTAL_VOLUMES,
        help="CRITICAL if total volume count <= this value (default: disabled)",
    )
 
    # Total volume count — maximum thresholds (alert when too MANY)
    parser.add_argument(
        "--warning-max-total-volumes",
        type=int,
        default=DEFAULT_WARNING_MAX_TOTAL_VOLUMES,
        help="WARNING if total volume count >= this value (default: disabled)",
    )
    parser.add_argument(
        "--critical-max-total-volumes",
        type=int,
        default=DEFAULT_CRITICAL_MAX_TOTAL_VOLUMES,
        help="CRITICAL if total volume count >= this value (default: disabled)",
    )
 
    # Overdue-for-recycling thresholds (alert when too MANY)
    parser.add_argument(
        "--warning-overdue",
        type=int,
        default=DEFAULT_WARNING_OVERDUE,
        help="WARNING if overdue-for-recycling volume count >= this value (default: disabled)",
    )
    parser.add_argument(
        "--critical-overdue",
        type=int,
        default=DEFAULT_CRITICAL_OVERDUE,
        help="CRITICAL if overdue-for-recycling volume count >= this value (default: disabled)",
    ) 
    parser.add_argument(
        "--no-perfdata",
        action="store_true",
        default=False,
        help="Disable performance data output (default: perfdata enabled)",
    )
 
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
 
    args = parser.parse_args()
 
    try:
        _validate_thresholds(args)
    except ValueError as exc:
        parser.error(str(exc))
 
    return args
 
 
def _validate_thresholds(args) -> None:
    # For min total volumes: warning must be >= critical (both are lower bounds)
    if (
        args.warning_total_volumes is not None
        and args.critical_total_volumes is not None
        and args.warning_total_volumes < args.critical_total_volumes
    ):
        raise ValueError(
            f"--warning-total-volumes ({args.warning_total_volumes}) "
            f"must be >= --critical-total-volumes ({args.critical_total_volumes})"
        )
 
    # For max total volumes: warning must be <= critical (both are upper bounds)
    if (
        args.warning_max_total_volumes is not None
        and args.critical_max_total_volumes is not None
        and args.warning_max_total_volumes > args.critical_max_total_volumes
    ):
        raise ValueError(
            f"--warning-max-total-volumes ({args.warning_max_total_volumes}) "
            f"must be <= --critical-max-total-volumes ({args.critical_max_total_volumes})"
        )
 
    # Min threshold must be below max threshold to avoid an impossible range
    if (
        args.warning_total_volumes is not None
        and args.warning_max_total_volumes is not None
        and args.warning_total_volumes >= args.warning_max_total_volumes
    ):
        raise ValueError(
            f"--warning-total-volumes ({args.warning_total_volumes}) "
            f"must be < --warning-max-total-volumes ({args.warning_max_total_volumes})"
        )
 
    # For overdue: warning must be <= critical (both are upper bounds)
    if (
        args.warning_overdue is not None
        and args.critical_overdue is not None
        and args.warning_overdue > args.critical_overdue
    ):
        raise ValueError(
            f"--warning-overdue ({args.warning_overdue}) "
            f"must be <= --critical-overdue ({args.critical_overdue})"
        )
 
 
# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
 
def fetch_pool_data(args, conn):
    """
    Return (total_count, overdue_rows) for the given pool,
    optionally filtered by media type and/or storage daemon.
    """
    extra_where = ""
    extra_params = []
 
    if args.mediatype:
        extra_where += " AND Media.MediaType = %s"
        extra_params.append(args.mediatype)
 
    if args.storage:
        extra_where += " AND Storage.Name = %s"
        extra_params.append(args.storage)
 
    storage_join = (
        "LEFT JOIN Storage ON Media.StorageId = Storage.StorageId"
        if args.storage else ""
    )
 
    sql_total = f"""
        SELECT COUNT(*) AS total
        FROM Media
        JOIN Pool USING (PoolId)
        {storage_join}
        WHERE Pool.Name = %s
          AND Media.VolStatus NOT IN ('Scratch', 'Recycle')
          {extra_where}
    """
 
    sql_overdue = f"""
        SELECT
            Media.VolumeName,
            Media.VolStatus,
            Media.LastWritten,
            Media.VolRetention,
            (EXTRACT(EPOCH FROM NOW()) - EXTRACT(EPOCH FROM Media.LastWritten))
                AS seconds_since_written,
            Media.VolRetention AS retention_seconds
        FROM Media
        JOIN Pool USING (PoolId)
        {storage_join}
        WHERE Pool.Name = %s
          AND Media.VolStatus IN ('Full', 'Used')
          AND Media.LastWritten IS NOT NULL
          AND Media.LastWritten + (Media.VolRetention * INTERVAL '1 second') < NOW()
          {extra_where}
        ORDER BY Media.LastWritten ASC
    """
 
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(sql_total, [args.pool] + extra_params)
            row = cur.fetchone()
            total = int(row["total"]) if row else 0
 
            cur.execute(sql_overdue, [args.pool] + extra_params)
            overdue_rows = cur.fetchall()
 
        return total, overdue_rows
 
    except Exception as exc:
        plugin_exit(UNKNOWN, f"[UNKNOWN] Query failed: {exc}")
 
 
# ---------------------------------------------------------------------------
# Main check logic
# ---------------------------------------------------------------------------
 
def check_pool(args):
    conn = connect_db(args)
    try:
        total, overdue_rows = fetch_pool_data(args, conn)
    finally:
        conn.close()
 
    if total == 0:
        plugin_exit(
            UNKNOWN,
            f"[UNKNOWN] Pool '{args.pool}' not found or contains no volumes"
        )
 
    overdue_count = len(overdue_rows)
    hits = []
    codes = []
 
    # 1a. Total volume count — alert when too few
    rc = apply_min_thresholds(
        total,
        args.warning_total_volumes,
        args.critical_total_volumes,
    )
    if rc > OK:
        threshold = (
            args.critical_total_volumes if rc == CRITICAL
            else args.warning_total_volumes
        )
        hits.append(
            f"total_volumes={total}<={threshold} ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    # 1b. Total volume count — alert when too many
    rc = apply_max_thresholds(
        total,
        args.warning_max_total_volumes,
        args.critical_max_total_volumes,
    )
    if rc > OK:
        threshold = (
            args.critical_max_total_volumes if rc == CRITICAL
            else args.warning_max_total_volumes
        )
        hits.append(
            f"total_volumes={total}>={threshold} ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    # 2. Overdue for recycling — alert when too many
    rc = apply_max_thresholds(
        overdue_count,
        args.warning_overdue,
        args.critical_overdue,
    )
    if rc > OK:
        threshold = (
            args.critical_overdue if rc == CRITICAL
            else args.warning_overdue
        )
        hits.append(
            f"overdue_volumes={overdue_count}>={threshold} ({status_label(rc).lower()})"
        )
    codes.append(rc)
 
    overall = combine_codes(*codes)
 
    # Build overdue volume list for output (cap at 5)
    overdue_names = [r["volumename"] for r in overdue_rows[:5]]
    overdue_text = ", ".join(overdue_names)
    if overdue_count > 5:
        overdue_text += f" ... and {overdue_count - 5} more"
 
    threshold_text = f", threshold_hits={'; '.join(hits)}" if hits else ""
 
    filter_parts = []
    if args.mediatype:
        filter_parts.append(f"mediatype={args.mediatype}")
    if args.storage:
        filter_parts.append(f"storage={args.storage}")
    filter_text = f" [{', '.join(filter_parts)}]" if filter_parts else ""
 
    message = (
        f"[{status_label(overall)}] "
        f"Pool '{args.pool}'{filter_text}: "
        f"total_volumes={total}, "
        f"overdue_for_recycle={overdue_count}"
        + (f" ({overdue_text})" if overdue_count > 0 else "")
        + threshold_text
    )
 
    if not args.no_perfdata:
        # Build Nagios range strings for total_volumes.
        # If both min and max are set: "~:warn_min" would only cover the low side,
        # so we use the full range "warn_min:warn_max" instead.
        # If only min is set: "~:N" (alert below N).
        # If only max is set: "N" (alert above N, Nagios default direction).
        def volume_range(min_val, max_val):
            if min_val is not None and max_val is not None:
                return f"{min_val}:{max_val}"
            elif min_val is not None:
                return f"~:{min_val}"
            elif max_val is not None:
                return f"{max_val}"
            return ""
 
        warn_range = volume_range(args.warning_total_volumes,  args.warning_max_total_volumes)
        crit_range = volume_range(args.critical_total_volumes, args.critical_max_total_volumes)
 
        overdue_warn = "" if args.warning_overdue  is None else args.warning_overdue
        overdue_crit = "" if args.critical_overdue is None else args.critical_overdue
 
        perfdata = (
            f"'total_volumes'={total};{warn_range};{crit_range};; "
            f"'overdue_volumes'={overdue_count}c;"
            f"{overdue_warn};{overdue_crit};;"
        )
    else:
        perfdata = ""
 
    plugin_exit(overall, message, perfdata)
 
 
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
 
def main():
    args = parse_args()
 
    if not args.password:
        try:
            args.password = read_password_from_file(args.password_file)
        except Exception as exc:
            plugin_exit(UNKNOWN, f"[UNKNOWN] Could not read password: {exc}")
 
    check_pool(args)
 
 
if __name__ == "__main__":
    main()
 
