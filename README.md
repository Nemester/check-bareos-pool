# check_bareos_pool.py

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-blueviolet?style=for-the-badge" alt="License: MIT">
  <img src="https://img.shields.io/badge/Built%20by-NEMESTER-DARKGREEN?style=for-the-badge" alt="Built by Nemester">
</p>

A lightweight Icinga2 / Nagios plugin for monitoring the number of tapes in pools via the Bareos PostgreSQL catalog.

This plugin is focused on two practical failure modes:

- **Too few volumes in the pool** --> tapes are being consumed but not replenished from scratch, indicating a library or recycling supply problem.
- **Too many volumes overdue for recycling** --> tapes that should have been returned to the scratch pool are still sitting in `Full` or `Used` status, indicating the Bareos recycle automechanism is broken or not configured

It is intended for environments with tape libraries where proactive detection of recycling failures and pool exhaustion is critical, and where discovering a broken automechanism only when a backup fails is not acceptable. 

> **Note: It can also be used to monitor the number of tapes in the scratch pool.**  
> E.g. you want to make sure that you have enough tapes for a monthly full backup or you want to keep track of the number of free tapes and when
> to order a new batch


---

## Table of Contents

- [Features](#features)
- [How overdue detection works](#how-overdue-detection-works)
- [Requirements](#requirements)
- [Bareos Catalog Permissions](#bareos-catalog-permissions)
- [Installation](#installation)
- [Usage](#usage)
  - [Required arguments](#required-arguments)
  - [Authentication](#authentication)
  - [Connection options](#connection-options)
  - [Filter options](#filter-options)
  - [Threshold options](#threshold-options)
  - [Other options](#other-options)
- [Examples](#examples)
- [Example Output](#example-output)
- [Performance Data](#performance-data)
- [Icinga2 Example](#icinga2-example)
- [Known Limitations](#known-limitations)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Backlog / Ideas](#backlog--ideas)
- [License](#license)

---

## Features

- Monitor total volume count in a pool --> alert when too few (replenishment failing) or too many (unexpected accumulation)
- Monitor volumes overdue for recycling --> alert when the recycle automechanism is not working
- Optional filters by media type and/or storage daemon for environments with mixed libraries or multiple tape generations
- Active filters shown in the plugin output line
- All thresholds disabled by default --> configure only what you need
- `--no-perfdata` flag for monitoring systems that do not process perfdata or pools with too many tapes

---

## How overdue detection works

A volume is considered **overdue for recycling** when all of the following are true:

- `VolStatus` is `Full` or `Used`
- `LastWritten` is not null
- `LastWritten + VolRetention < NOW()`

The volume's own `VolRetention` value from the Bareos catalog is used directly (no extra retention parameter is needed). When the overdue count crosses the configured thresholds, it means Bareos has not recycled volumes back to scratch as expected, which is usually caused by:

- `Recycle = yes` not set on the pool
- `AutoPrune = yes` not set
- No scratch pool configured as `RecyclePool`
- Insufficient scratch pool inventory to trigger recycling
- A director configuration error

---

## Requirements

- Python 3.10 or newer
- PostgreSQL client libraries
- Python package: `psycopg2`

### Install dependency

Using pip:

```bash
pip install psycopg2-binary
```

Using system package (Debian/Ubuntu):

```bash
apt install python3-psycopg2
```

Using system package (RHEL/CentOS):

```bash
yum install python3-psycopg2
```

---

## Bareos Catalog Permissions

The plugin connects directly to the Bareos PostgreSQL catalog and reads the `Media`, `Pool`, and (optionally) `Storage` tables.

```sql
GRANT SELECT ON Media   TO monitoring;
GRANT SELECT ON Pool    TO monitoring;
GRANT SELECT ON Storage TO monitoring;
```

---

## Installation

Copy the script to your monitoring plugins directory on the Bareos director host, or on any host that can reach the Bareos PostgreSQL catalog:

```bash
cp check_bareos_pool.py /usr/local/lib/nagios/plugins/
chmod +x /usr/local/lib/nagios/plugins/check_bareos_pool.py
```

---

## Usage

```bash
check_bareos_pool.py -U USER [-p PASSWORD | --password-file FILE] --pool POOL [OPTIONS]
```

### Required arguments

- `-U`, `--user`  
  Database user

- `--pool`  
  Pool name to check (exact match)

### Authentication

- `-p`, `--password`  
  Database password (mutually exclusive with `--password-file`)

- `--password-file`  
  File containing a line like `Password = secret`

Default password file:

```text
/etc/bareos/bareos-dir.conf
```

### Connection options

- `-H`, `--host`  
  PostgreSQL host  
  Default: `127.0.0.1`

- `-P`, `--port`  
  PostgreSQL port  
  Default: `5432`

- `-d`, `--database`  
  Database name  
  Default: `bareos`

### Filter options

Both filters are optional and can be combined freely.

- `--mediatype TYPE`  
  Restrict the check to volumes of this media type only (e.g. `LTO-9`)

- `--storage NAME`  
  Restrict the check to volumes whose storage daemon matches this name (e.g. `sd-library1`)

> **Note: cleaning tape issue with `--storage` on the Scratch pool**  
> When filtering the Scratch pool by `--storage` only, cleaning tapes may be included in
> the volume count because they share the same storage daemon. This leads to a false
> total count.  
> **Always add `--mediatype` when filtering the Scratch pool by `--storage`**, for example:
> ```bash
> check_bareos_pool.py -U bareos --pool Scratch --storage sd-library1 --mediatype LTO-9
> ```
> On regular backup pools (`Tape-Inc`, `Tape-Full`, etc.) `--storage` alone works as expected
> because cleaning tapes are not assigned to those pools.

### Threshold options

All thresholds are **disabled by default**. Omitting a threshold simply skips that check. A bare invocation with no threshold flags will always return OK as long as the pool exists and has volumes. Useful as a first run to see current values before deciding on limits.

#### Minimum total volumes (alert when too few)

- `--warning-total-volumes N`  
  Return `WARNING` if total volume count <= N  
  Default: disabled

- `--critical-total-volumes N`  
  Return `CRITICAL` if total volume count <= N  
  Default: disabled

Validation rule:

```text
warning-total-volumes >= critical-total-volumes
```

#### Maximum total volumes (alert when too many)

- `--warning-max-total-volumes N`  
  Return `WARNING` if total volume count >= N  
  Default: disabled

- `--critical-max-total-volumes N`  
  Return `CRITICAL` if total volume count >= N  
  Default: disabled

Validation rule:

```text
warning-max-total-volumes <= critical-max-total-volumes
```

When both min and max thresholds are set, the valid range is `min < total < max`. The validator will reject a configuration where `warning-total-volumes >= warning-max-total-volumes`.

#### Overdue for recycling (alert when too many)

- `--warning-overdue N`  
  Return `WARNING` if overdue-for-recycling volume count >= N  
  Default: disabled

- `--critical-overdue N`  
  Return `CRITICAL` if overdue-for-recycling volume count >= N  
  Default: disabled

Validation rule:

```text
warning-overdue <= critical-overdue
```

### Other options

- `--no-perfdata`  
  Disable performance data output. Useful when the monitoring system does not process perfdata, or when checking a large pool where the output line would become very long.  
  Default: perfdata enabled

- `--version`  
  Show plugin version

---

## Examples

### Basic check: observe current values without alerting

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc
```

### Alert when pool runs low

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc \
  --warning-total-volumes 10 \
  --critical-total-volumes 3
```

### Alert on both too few and too many volumes

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc \
  --warning-total-volumes 10 \
  --critical-total-volumes 3 \
  --warning-max-total-volumes 50 \
  --critical-max-total-volumes 80
```

### Alert when recycling automechanism is broken

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc \
  --warning-overdue 2 \
  --critical-overdue 5
```

### Full check: all thresholds

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc \
  --warning-total-volumes 10 \
  --critical-total-volumes 3 \
  --warning-max-total-volumes 50 \
  --critical-max-total-volumes 80 \
  --warning-overdue 2 \
  --critical-overdue 5
```

### Scratch pool with two libraries: filter by storage and media type

```bash
# Always combine --storage with --mediatype on the Scratch pool (see Known Limitations)
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password \
  --pool Scratch \
  --storage sd-library1 \
  --mediatype LTO-9 \
  --warning-total-volumes 5 \
  --critical-total-volumes 2
```

---

## Example Output

### OK: no thresholds configured

```text
[OK] Pool 'Tape-Inc': total_volumes=24, overdue_for_recycle=0
```

### OK: with active filters

```text
[OK] Pool 'Scratch' [mediatype=LTO-9, storage=sd-library1]: total_volumes=8, overdue_for_recycle=0
```

### WARNING: overdue volumes accumulating

```text
[WARNING] Pool 'Tape-Inc': total_volumes=24, overdue_for_recycle=3 (UV0012L9, UV0015L9, UV0021L9), threshold_hits=overdue_volumes=3>=2 (warning)
```

### CRITICAL: pool nearly empty

```text
[CRITICAL] Pool 'Tape-Inc': total_volumes=2, overdue_for_recycle=0, threshold_hits=total_volumes=2<=2 (critical)
```

### CRITICAL: both thresholds hit simultaneously

```text
[CRITICAL] Pool 'Tape-Inc': total_volumes=2, overdue_for_recycle=6 (UV0001L9, UV0003L9, UV0007L9, UV0009L9, UV0011L9 ... and 1 more), threshold_hits=total_volumes=2<=2 (critical); overdue_volumes=6>=5 (critical)
```

### UNKNOWN: pool not found

```text
[UNKNOWN] Pool 'Tape-X' not found or contains no volumes
```

---

## Performance Data

Two metrics are emitted per check run:

| Label | Unit | Threshold direction |
|---|---|---|
| `total_volumes` | count | lower bound, upper bound, or both |
| `overdue_volumes` | `c` (counter) | upper bound |

The `total_volumes` perfdata range adapts to the thresholds that are set:

| Thresholds configured | Perfdata range syntax |
|---|---|
| Min only | `~:warn;~:crit` |
| Max only | `warn;crit` |
| Both min and max | `min:max` |
| None | `;` |

Example: min only:

```text
'total_volumes'=24;~:10;~:3;; 'overdue_volumes'=0c;2;5;;
```

Example: both min and max:

```text
'total_volumes'=24;10:50;3:80;; 'overdue_volumes'=0c;2;5;;
```

Example: no thresholds:

```text
'total_volumes'=96;;;; 'overdue_volumes'=0c;;;;
```

Use `--no-perfdata` to suppress this output entirely.

---

## Icinga2 Example

You can set up the check on any host that can access the PostgreSQL DB on the bareos director. If you don't want to expose the database
use the provided wrapper script (`check_bareos_pool_nrpe.sh`) and trigger the check through nrpe (see example below)

### NRPE setup on the Bareos host

Add to `/etc/nagios/nrpe_local.cfg` on the Bareos director:

```ini
command[check_bareos_pool]=/usr/local/lib/nagios/plugins/check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password $ARG1$
```

Make sure `dont_blame_nrpe=1` is set in `nrpe.cfg` to allow argument passing.

### Wrapper script on the Icinga host

Use the included `check_bareos_pool_nrpe.sh` wrapper on the Icinga master/satellite. Place it in your plugins contrib directory:

```bash
cp check_bareos_pool_nrpe.sh /usr/local/lib/nagios/plugins/
chmod +x /usr/local/lib/nagios/plugins/check_bareos_pool_nrpe.sh
```

### CheckCommand definition

```icinga2
object CheckCommand "check_bareos_pool" {
  import "plugin-check-command"
  command = [ PluginContribDir + "/check_bareos_pool_nrpe.sh" ]
  arguments = {
    "-H" = {
      value       = "$bareos_dir$"
      required    = true
      description = "NRPE host running the Bareos check"
    }
    "-p" = {
      value       = "$bareos_nrpe_port$"
      required    = false
      description = "NRPE port (default: 5666)"
    }
    "-t" = {
      value       = "$bareos_nrpe_timeout$"
      required    = false
      description = "NRPE timeout in seconds (default: 10)"
    }
    "--nrpe-cmd" = {
      value       = "$bareos_pool_nrpe_cmd$"
      required    = false
      description = "NRPE command name (default: check_bareos_pool)"
    }
    "--pool" = {
      value       = "$bareos_pool_name$"
      required    = true
      description = "Pool name to check (exact match)"
    }
    "--mediatype" = {
      value       = "$bareos_pool_mediatype$"
      required    = false
      description = "Restrict check to volumes of this media type (e.g. LTO-9)"
    }
    "--storage" = {
      value       = "$bareos_pool_storage$"
      required    = false
      description = "Restrict check to volumes of this storage daemon name"
    }
    "--warning-total-volumes" = {
      value       = "$bareos_pool_warning_total_volumes$"
      required    = false
      description = "WARNING if total volume count <= this value (default: disabled)"
    }
    "--critical-total-volumes" = {
      value       = "$bareos_pool_critical_total_volumes$"
      required    = false
      description = "CRITICAL if total volume count <= this value (default: disabled)"
    }
    "--warning-max-total-volumes" = {
      value       = "$bareos_pool_warning_max_total_volumes$"
      required    = false
      description = "WARNING if total volume count >= this value (default: disabled)"
    }
    "--critical-max-total-volumes" = {
      value       = "$bareos_pool_critical_max_total_volumes$"
      required    = false
      description = "CRITICAL if total volume count >= this value (default: disabled)"
    }
    "--warning-overdue" = {
      value       = "$bareos_pool_warning_overdue$"
      required    = false
      description = "WARNING if overdue-for-recycling count >= this value (default: disabled)"
    }
    "--critical-overdue" = {
      value       = "$bareos_pool_critical_overdue$"
      required    = false
      description = "CRITICAL if overdue-for-recycling count >= this value (default: disabled)"
    }
    "--no-perfdata" = {
      set_if      = "$bareos_pool_no_perfdata$"
      description = "Disable performance data output"
    }
  }
}
```

### Service apply rule

```icinga2
apply Service "Bareos pool " for (pool_name => config in host.vars.bareos_pool_checks) {
  import "generic-service"
  check_interval     = 24h
  max_check_attempts = 3
  retry_interval     = 24h
  vars.notification_interval = 24h
  check_command = "check_bareos_pool"

  vars.bareos_dir          = host.vars.bareos_dir ? host.vars.bareos_dir : "birke.wsl.ch"
  vars.bareos_nrpe_port    = host.vars.bareos_nrpe_port ? host.vars.bareos_nrpe_port : 5666
  vars.bareos_nrpe_timeout = host.vars.bareos_nrpe_timeout ? host.vars.bareos_nrpe_timeout : 10

  if (config.contains("pool")) {
    vars.bareos_pool_name = config.pool
  } else {
    vars.bareos_pool_name = pool_name
  }
  vars.bareos_pool_mediatype = config.pool_mediatype ? config.pool_mediatype : null
  vars.bareos_pool_storage   = config.pool_storage   ? config.pool_storage   : null

  // Minimum total volumes (alert when too few): disabled by default
  vars.bareos_pool_warning_total_volumes  = config.pool_warning_total_volumes  ? config.pool_warning_total_volumes  : null
  vars.bareos_pool_critical_total_volumes = config.pool_critical_total_volumes ? config.pool_critical_total_volumes : null

  // Maximum total volumes (alert when too many): disabled by default
  vars.bareos_pool_warning_max_total_volumes  = config.pool_warning_max_total_volumes  ? config.pool_warning_max_total_volumes  : null
  vars.bareos_pool_critical_max_total_volumes = config.pool_critical_max_total_volumes ? config.pool_critical_max_total_volumes : null

  // Overdue for recycling: disabled by default
  vars.bareos_pool_warning_overdue  = config.pool_warning_overdue  ? config.pool_warning_overdue  : null
  vars.bareos_pool_critical_overdue = config.pool_critical_overdue ? config.pool_critical_overdue : null

  vars.bareos_pool_no_perfdata = config.pool_no_perfdata ? config.pool_no_perfdata : false

  if (config.contains("display_name")) {
    display_name = config.display_name
  }

  vars.notification.mail.users  = [ "Backup" ]

  assign where host.vars.bareos_pool_checks
}
```

### Example host vars

```icinga2
vars.bareos_dir = "bareos-director.example.com"

vars.bareos_pool_checks["Tape-Inc"] = {
  pool_warning_total_volumes      = 10
  pool_critical_total_volumes     = 3
  pool_warning_max_total_volumes  = 50
  pool_critical_max_total_volumes = 80
  pool_warning_overdue            = 2
  pool_critical_overdue           = 5
}

vars.bareos_pool_checks["Tape-Full"] = {
  pool_warning_total_volumes  = 5
  pool_critical_total_volumes = 2
  pool_warning_overdue        = 2
  pool_critical_overdue       = 5
}

// Always specify mediatype for Scratch to avoid counting cleaning tapes
// when also filtering by storage daemon
vars.bareos_pool_checks["Scratch-Library1"] = {
  pool          = "Scratch"
  display_name  = "Bareos pool Scratch (Library 1)"
  pool_mediatype = "LTO-9"
  pool_storage   = "sd-library1"
  pool_warning_total_volumes  = 5
  pool_critical_total_volumes = 2
}

vars.bareos_pool_checks["Scratch-Library2"] = {
  pool          = "Scratch"
  display_name  = "Bareos pool Scratch (Library 2)"
  pool_mediatype = "LTO-9"
  pool_storage   = "sd-library2"
  pool_warning_total_volumes  = 5
  pool_critical_total_volumes = 2
}
```

Note the use of `pool` and `display_name` keys to check the same Bareos pool twice with different storage filters while keeping distinct service names in Icinga.

---

## Known Limitations

### Cleaning tapes included when filtering Scratch pool by `--storage` only

Bareos stores cleaning tapes in the Scratch pool and associates them with a storage daemon. When `--storage` is used without `--mediatype` on the Scratch pool, cleaning tapes are counted as regular volumes, inflating the total count.

This does not affect backup pools (e.g. `Tape-Inc`, `Tape-W`) since cleaning tapes are not assigned to them.

**Recommendation:** always combine `--storage` with `--mediatype` when checking the Scratch pool:

```bash
# Correct
check_bareos_pool.py -U bareos --pool Scratch --storage sd-library1 --mediatype LTO-9

# May include cleaning tape in count
check_bareos_pool.py -U bareos --pool Scratch --storage sd-library1
```

---

## Security Notes

- The plugin uses parameterized SQL queries to avoid SQL injection.
- Avoid passing passwords on the command line if possible, because they may appear in process listings.
- Prefer `--password-file` or a protected wrapper script.
- Restrict file permissions on configuration files containing credentials.

Recommended permissions:

```bash
chmod 600 /etc/bareos/db-password
```

---

## Troubleshooting

### `UNKNOWN - Required Python module 'psycopg2' is not installed`

Install the module:

```bash
pip install psycopg2-binary
# or
apt install python3-psycopg2
```

### `UNKNOWN - Database connection failed`

Check:

- PostgreSQL is reachable from the monitoring host
- host, port, database, user, and password are correct
- firewall rules allow the connection
- the database user has `SELECT` on `Media`, `Pool`, and `Storage`

### `UNKNOWN - Pool 'X' not found or contains no volumes`

Check the pool name with:

```sql
SELECT Name FROM Pool;
```

Note that volumes already in `Scratch` or `Recycle` status are always excluded from the total count.

### `NRPE: Unable to read output`

Typical causes:

- the NRPE command definition for `check_bareos_pool` is missing in `nrpe_local.cfg`
- `dont_blame_nrpe=1` is not set in `nrpe.cfg`
- the NRPE user cannot read the password file
- the NRPE timeout is too low for a large pool

### Total volume count is higher than expected on the Scratch pool

You are likely filtering by `--storage` without `--mediatype`. Cleaning tapes in the Scratch pool are associated with the storage daemon and will be counted. Add `--mediatype LTO-9` (or your tape generation) to exclude them. See [Known Limitations](#known-limitations).

### `WARNING` fires immediately on a small pool

The configured `--warning-total-volumes` may be higher than the actual pool size. Run without thresholds first to observe the real count, then configure accordingly:

```bash
check_bareos_pool.py -U bareos --password-file /etc/bareos/db-password --pool Tape-Inc
```

---

## Backlog / Ideas

Possible future improvements:

- alert on pools with zero `Append` volumes available for writing
- per-pool age report for volumes not written to in unexpectedly long time
- JSON output mode for external integrations
- summary mode across all pools in a single check

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## ⭐ Support the Project

If you find this project useful, please consider giving it a star on GitHub.
It helps others discover the project and motivates me to keep improving it. Thank you for your support!