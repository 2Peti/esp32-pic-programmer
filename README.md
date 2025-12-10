PIC Programmer CLI (Arduino-Based)
==================================

A powerful command-line tool for flashing, verifying, erasing, reading, and dumping **PIC microcontroller memory** using an Arduino as the programmer.

Supports Intel HEX parsing + generation, full-chip wipe, row erase, chunked flash writing, configuration-word handling, and combined multi-action command execution.

* * *

Features
========

*   Flash program memory from an Intel HEX file
*   Verify device memory against HEX file
*   **Bulk erase** entire flash (`--wipe`)
*   **Erase individual rows** (`--erase-row`)
*   Write bytes or words (`--write`)
*   Read word blocks (`--read`)
*   Dump entire flash + config to a HEX file (`--dump`)
*   Generate valid Intel HEX output
*   Auto-detect device properties from `pic_devices.ini`
*   Combine multiple actions in one command
*   Safe dry-run mode (`--dry-run`)

* * *

Installation
============

```bash
pip install pyserial
git clone https://github.com/2Peti/esp32-pic-programmer.git
```

Requires:

*   Python 3.8+
*   Arduino running the matching firmware
*   A device profile (via `pic_devices.ini`)

* * *

Usage
=====

Basic Syntax
------------

```bash
python3 main.py <hexfile> -d device.ini -p <serial port> [actions] [options]
```

* * *

Examples
========

Most common flashing workflow (wipe + flash + config):
------------------------------------------------------

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 --wipe -f --config firmware.hex
```

Flash only
----------

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 -f firmware.hex
```

Verify against HEX file
-----------------------

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 -v firmware.hex
```

Wipe entire flash:
------------------

```bash
python3 main.py -p /dev/ttyUSB0 --wipe
```

Erase a single row
------------------

```bash
python3 main.py -p /dev/ttyUSB0 --erase-row 0x0400
```

Write raw hex bytes (must be even length)
-----------------------------------------

```bash
python3 main.py -p /dev/ttyUSB0 --write 0x0100 AABBCCDD
```

Read N words starting at an address
-----------------------------------

```bash
python3 main.py -p /dev/ttyUSB0 --read 0x0200 128
```

Dump entire flash + config into a HEX file
------------------------------------------

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 --dump out.hex
```

* * *

Multi-Action Support
====================

You can **combine multiple actions** in a single command.  
The tool executes them _in this order_:

1.  `--wipe` (bulk erase)
2.  `--erase-row`
3.  `--flash`
4.  `--verify`
5.  `--write`
6.  `--read`
7.  `--dump`

### Example: Erase → Flash → Read back block → Dump

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 --wipe -f firmware.hex --read 0x0000 64 --dump backup.hex
```

### Example: Flash but also extract a HEX dump afterwards

```bash
python3 main.py -d device.ini -p /dev/ttyUSB0 -f firmware.hex --dump saved.hex
```

* * *

Device Configuration: `pic_devices.ini`
=======================================

Example:

```ini
[PIC16F886]
ROMSIZE = 2000
FLASH_WRITE = 20
CONFIG = 0x1FFF - 0x2007
```

Field descriptions
------------------

| Field | Description |
| --- | --- |
| `ROMSIZE` | Maximum word-addressed program memory range |
| `FLASH_WRITE` | PIC flash row size (words) |
| `CONFIG` | Address range for configuration words |

Required for:  
`--flash`, `--verify`, `--dump`.

* * *

Intel HEX Loading and Saving
============================

### Loading (`load_hex()`)

*   Accepts extended linear address records (type 04)
*   Converts byte addresses → word addresses
*   PIC words stored little-endian internally
*   Automatically handles segmented HEX files

### Saving (`save_hex()`)

*   Automatically emits:
    *   Type 04 records (extended linear addresses)
    *   Type 00 data records
    *   Type 01 EOF record
*   Writes max **16 bytes (8 words)** per line
*   Filters out unused memory (0x3FFF) during `--dump`
*   Preserves config words even if blank

* * *

Technical Documentation
=======================

This describes the **serial protocol** used between the PC client and the Arduino firmware.

* * *

Serial Protocol Specification
=============================

*   **Baud:** 115200
*   **Endian:** Big-endian (addresses + words)
*   **Timeout:** 5 seconds per operation
*   **No unsolicited output allowed**

* * *

Commands Overview
-----------------

| Command | Host → Dev | Description |
| --- | --- | --- |
| `s` | handshake request | Initiate session |
| `x` | disconnect | End session |
| `w` | write block | Write flash/config words |
| `r` | read block | Read N words |
| `e` | erase row | Erase one flash row |
| `b` | bulk erase | Erase all user flash |

* * *

Handshake
---------

### Host → Arduino

```
73   ; 's'
```

### Arduino → Host

```
4B   ; 'K'
```

Failure to receive `'K'` aborts the session.

* * *

Write Block (`w`)
=================

### Host → Device

```
'w'
ADDR_H ADDR_L
LEN_H LEN_L       ; number of 16-bit words
<data bytes...>   ; 2 * LEN bytes
```

### Device → Host

```
'K'
```

* * *

Read Block (`r`)
================

### Host → Device

```
'r'
ADDR_H ADDR_L
LEN_H LEN_L
```

### Device → Host

```
<data bytes...>   ; LEN * 2 bytes
```

Partial reads = failure.

* * *

Erase Row (`e`)
===============

### Host → Device

```
'e'
ADDR_H ADDR_L     ; word-aligned row address
```

### Device → Host

```
'K'
```

* * *

Bulk Erase (`b`)
================

### Host → Device

```
'b'
ADDR_H ADDR_L     ; currently unused
```

Typically the address `0x80FF` is sent for compatibility.

### Device → Host

```
'K'
```

* * *

Disconnect (`x`)
================

Ends session and flushes buffers.

* * *

Memory Model
============

*   All addresses are **word addresses**
*   All transfers are **16-bit words**
*   Arduino returns words in **big-endian**
*   Flash is chunked according to `FLASH_WRITE` rows
*   Empty flash value is **0x3FFF**

* * *

Dump Filtering Logic
====================

When dumping (`--dump`):

*   All words equal to `0x3FFF` are removed
*   Configuration-range addresses are always preserved
*   Greatly reduces file size from full device dumps

* * *
