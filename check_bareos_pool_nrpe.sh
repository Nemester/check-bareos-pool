#!/usr/bin/env bash
#
# check_bareos_pool_nrpe.sh
#
# Wrapper for check_bareos_pool.py via NRPE
#
# Copyright (C) 2026 Manuel Sonder
#
# SPDX-License-Identifier: MIT
#
# This script executes a remote check for a specific Bareos tape pool
# using the check_bareos_pool.py plugin on a remote host via NRPE.
#
# It checks the total volume count and the number of volumes overdue
# for recycling back to the scratch pool, which indicates a broken or
# misconfigured Bareos recycle automechanism.
#
# Features:
#   - Check total volume count in a pool (alert when too few or too many)
#   - Check overdue-for-recycling volume count (alert when too many)
#   - Optional filtering by media type (e.g. LTO-9)
#   - Optional filtering by storage daemon name
#   - All thresholds disabled by default -- must be explicitly configured
#   - Pass-through of performance data from remote plugin
#
# The wrapper builds the argument string and forwards it via NRPE.
#
# Requirements:
#   - NRPE installed on remote host
#   - NRPE command configured to execute check_bareos_pool.py
#   - check_bareos_pool.py available on remote system
#
# Usage:
#   check_bareos_pool_nrpe.sh -H <nrpe_host> --pool <poolname> [options]
#
# Example:
#   check_bareos_pool_nrpe.sh -H backuphost --pool Tape-D \
#     --warning-total-volumes 10 \
#     --critical-total-volumes 3 \
#     --warning-max-total-volumes 50 \
#     --critical-max-total-volumes 80 \
#     --warning-overdue 2 \
#     --critical-overdue 5
#
# Scratch pool example (always use --mediatype to exclude cleaning tapes):
#   check_bareos_pool_nrpe.sh -H backuphost --pool Scratch \
#     --storage sd-library1 \
#     --mediatype LTO-9 \
#     --warning-total-volumes 5 \
#     --critical-total-volumes 2
#
# Exit Codes:
#   0 - OK
#   1 - WARNING
#   2 - CRITICAL
#   3 - UNKNOWN
#
# Notes:
#   - The actual evaluation logic is implemented in check_bareos_pool.py
#   - This wrapper only handles argument parsing and NRPE communication
#   - All thresholds are disabled by default; omitting one simply skips that check
#   - When checking the Scratch pool with --storage, always add --mediatype
#     to avoid cleaning tapes being counted as regular volumes
#
# Changelog:
#   1.0 - 2026-05-20 - Initial implementation
 
 
set -euo pipefail
 
NRPE_BIN="${NRPE_BIN:-/usr/lib/nagios/plugins/check_nrpe}"
NRPE_HOST="${NRPE_HOST:-}"
NRPE_PORT="${NRPE_PORT:-5666}"
NRPE_TIMEOUT="${NRPE_TIMEOUT:-10}"
NRPE_CMD="${NRPE_CMD:-check_bareos_pool}"
 
POOL="${POOL:-}"
MEDIATYPE="${MEDIATYPE:-}"
STORAGE="${STORAGE:-}"
 
WARNING_TOTAL_VOLUMES="${WARNING_TOTAL_VOLUMES:-}"
CRITICAL_TOTAL_VOLUMES="${CRITICAL_TOTAL_VOLUMES:-}"
 
WARNING_MAX_TOTAL_VOLUMES="${WARNING_MAX_TOTAL_VOLUMES:-}"
CRITICAL_MAX_TOTAL_VOLUMES="${CRITICAL_MAX_TOTAL_VOLUMES:-}"
 
WARNING_OVERDUE="${WARNING_OVERDUE:-}"
CRITICAL_OVERDUE="${CRITICAL_OVERDUE:-}"
 
NO_PERFDATA="${NO_PERFDATA:-}"
 
usage() {
  echo "Usage:"
  echo "  $0 -H <nrpe_host> --pool <poolname> [options]"
  echo ""
  echo "Required:"
  echo "  -H, --host                          NRPE host"
  echo "      --pool                          Bareos pool name to check"
  echo ""
  echo "Optional:"
  echo "  -p, --port                          NRPE port (default: 5666)"
  echo "  -t, --timeout                       NRPE timeout in seconds (default: 10)"
  echo "      --nrpe-cmd                      NRPE command name (default: check_bareos_pool)"
  echo ""
  echo "      --mediatype                     Restrict check to volumes of this media type (e.g. LTO-9)"
  echo "      --storage                       Restrict check to volumes of this storage daemon name"
  echo ""
  echo "      --warning-total-volumes         WARNING if total volume count <= this value (default: disabled)"
  echo "      --critical-total-volumes        CRITICAL if total volume count <= this value (default: disabled)"
  echo ""
  echo "      --warning-max-total-volumes     WARNING if total volume count >= this value (default: disabled)"
  echo "      --critical-max-total-volumes    CRITICAL if total volume count >= this value (default: disabled)"
  echo ""
  echo "      --warning-overdue               WARNING if overdue-for-recycling count >= this value (default: disabled)"
  echo "      --critical-overdue              CRITICAL if overdue-for-recycling count >= this value (default: disabled)"
  echo ""
  echo "      --no-perfdata                   Disable performance data output"
  echo ""
  echo "Note:"
  echo "  When checking the Scratch pool with --storage, always also pass --mediatype"
  echo "  to prevent cleaning tapes from being counted as regular volumes."
  echo ""
  echo "Examples:"
  echo "  $0 -H backuphost --pool Tape-D \\"
  echo "     --warning-total-volumes 10 --critical-total-volumes 3 \\"
  echo "     --warning-max-total-volumes 50 --critical-max-total-volumes 80 \\"
  echo "     --warning-overdue 2 --critical-overdue 5"
  echo ""
  echo "  $0 -H backuphost --pool Scratch --storage sd-library1 --mediatype LTO-9 \\"
  echo "     --warning-total-volumes 5 --critical-total-volumes 2"
}
 
append_arg() {
  local key="$1"
  local value="$2"
 
  if [[ -n "$value" ]]; then
    REMOTE_ARGS+=" $key $value"
  fi
}
 
append_flag() {
  local key="$1"
  local value="$2"
 
  if [[ -n "$value" ]]; then
    REMOTE_ARGS+=" $key"
  fi
}
 
while [[ $# -gt 0 ]]; do
  case "$1" in
    -H|--host)                          NRPE_HOST="$2";                   shift 2;;
    -p|--port)                          NRPE_PORT="$2";                   shift 2;;
    -t|--timeout)                       NRPE_TIMEOUT="$2";                shift 2;;
    --nrpe-cmd)                         NRPE_CMD="$2";                    shift 2;;
 
    --pool)                             POOL="$2";                        shift 2;;
    --mediatype)                        MEDIATYPE="$2";                   shift 2;;
    --storage)                          STORAGE="$2";                     shift 2;;
 
    --warning-total-volumes)            WARNING_TOTAL_VOLUMES="$2";       shift 2;;
    --critical-total-volumes)           CRITICAL_TOTAL_VOLUMES="$2";      shift 2;;
 
    --warning-max-total-volumes)        WARNING_MAX_TOTAL_VOLUMES="$2";   shift 2;;
    --critical-max-total-volumes)       CRITICAL_MAX_TOTAL_VOLUMES="$2";  shift 2;;
 
    --warning-overdue)                  WARNING_OVERDUE="$2";             shift 2;;
    --critical-overdue)                 CRITICAL_OVERDUE="$2";            shift 2;;
 
    --no-perfdata)                      NO_PERFDATA="1";                  shift;;
 
    -h|--help) usage; exit 0;;
    *) echo "UNKNOWN - unsupported argument: $1"; usage; exit 3;;
  esac
done
 
if [[ -z "${NRPE_HOST}" ]]; then
  echo "UNKNOWN - missing NRPE host"
  exit 3
fi
 
if [[ -z "${POOL}" ]]; then
  echo "UNKNOWN - missing pool name"
  exit 3
fi
 
if [[ ! -x "${NRPE_BIN}" ]]; then
  echo "UNKNOWN - check_nrpe not found: ${NRPE_BIN}"
  exit 3
fi
 
REMOTE_ARGS="--pool $POOL"
 
append_arg "--mediatype"                  "$MEDIATYPE"
append_arg "--storage"                    "$STORAGE"
 
append_arg "--warning-total-volumes"      "$WARNING_TOTAL_VOLUMES"
append_arg "--critical-total-volumes"     "$CRITICAL_TOTAL_VOLUMES"
 
append_arg "--warning-max-total-volumes"  "$WARNING_MAX_TOTAL_VOLUMES"
append_arg "--critical-max-total-volumes" "$CRITICAL_MAX_TOTAL_VOLUMES"
 
append_arg "--warning-overdue"            "$WARNING_OVERDUE"
append_arg "--critical-overdue"           "$CRITICAL_OVERDUE"
 
append_flag "--no-perfdata"               "$NO_PERFDATA"
 
set +e
OUTPUT="$("${NRPE_BIN}" \
  -H "${NRPE_HOST}" \
  -p "${NRPE_PORT}" \
  -t "${NRPE_TIMEOUT}" \
  -c "${NRPE_CMD}" \
  -a "${REMOTE_ARGS}" 2>&1)"
RC=$?
set -e
 
echo "${OUTPUT}"
exit "${RC}"
 
