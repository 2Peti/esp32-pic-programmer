PIC Programmer CLI (Arduino-Based)
==================================

A command-line utility for flashing, reading, and verifying **PIC microcontroller memory** using an Arduino as the programmer.  
Supports Intel HEX parsing, chunked flash writing, configuration-word handling, and verification.

* * *

Features
--------

*   Flash program memory from an **Intel HEX** file.
*   Verify device memory against a HEX file.
*   Read and write individual words.
*   Dump blocks of memory for inspection.
*   Auto-detect device parameters from `pic_devices.ini`.
*   Optional **dry-run mode** (no hardware required).
*   Supports PIC configuration memory ranges.

* * *

Requirements
------------

*   Python 3.8+
*   `pyserial`
*   Arduino running compatible PIC programmer firmware
*   A valid `pic_devices.ini` for your device

Install dependencies:

```bash
pip install pyserial
```

* * *

Usage
-----

### Basic Syntax

```bash
python3 main.py <hexfile> -d pic_devices.ini -p <serial_port> [options]
```

### Required Arguments

| Option | Description |
| --- | --- |
| `-d, --device` | Path to PIC device configuration INI file |
| `-p, --port` | Serial port (Arduino programmer) |
| One of: | `--flash`, `--verify`, `--read-word`, `--write-word`, `--dump` |

* * *

Common Commands
---------------

#### Flash a HEX file

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --flash firmware.hex
```

#### Flash + write config words

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --flash --config firmware.hex
```

#### Verify device memory against HEX file

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --verify firmware.hex
```

#### Read a single word

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --read-word 0x0010
```

#### Write a single word

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --write-word 0x0010 0x1234
```

#### Dump memory region

```bash
python3 main.py -d pic_devices.ini -p /dev/ttyUSB0 --dump 0x0000 128
```

#### Dry-run (no hardware)

```bash
python3 main.py firmware.hex -d pic_devices.ini -p TEST --flash --dry-run
```

* * *

Device Configuration (`pic_devices.ini`)
----------------------------------------

Example:

```ini
[PIC16F886]
ROMSIZE = 2000
FLASH_WRITE = 20
CONFIG = 0x1FFF - 0x2007
```

### Fields

| Key | Description |
| --- | --- |
| `ROMSIZE` | Total flash size (words) |
| `FLASH_WRITE` | Flash write row size (words) |
| `CONFIG` | Config memory address range |

* * *

Project Structure
-----------------

```
main.py             # Main CLI
pic_devices.ini     # Device config (user-provided)
```

* * *

Technical Documentation
-----------------------

This section describes the **serial protocol**, **message framing**, and **expected device behavior** used between the PC and Arduino firmware.

* * *

🔧 Serial Protocol Specification
================================

Communication is performed over a simple binary protocol with single-character commands followed by fixed-length fields.

*   **Baud Rate:** 115200
*   **Byte Order:** Big-endian (for all addresses + words)
*   **Timeout:** 5 seconds unless otherwise noted
*   **Handshake:** ASCII characters

* * *

1\. Connection Handshake
------------------------

Upon opening the serial connection:

**Host → Arduino**

```
0x73   ('s')
```

**Arduino → Host**

```
0x4B   ('K')
```

If the Arduino does not return `'K'`, the connection is considered failed.

* * *

2\. Commands Overview
---------------------

| Command | Direction | Description |
| --- | --- | --- |
| `s` | Host → Dev | Connect handshake |
| `x` | Host → Dev | Disconnect request |
| `w` | Host → Dev | Write flash/config block |
| `r` | Host → Dev | Read flash/config block |

* * *

3\. Write Block Command (`w`)
=============================

### Host → Device Frame

```
'w'
[ADDR_H] [ADDR_L]
[LEN_H]  [LEN_L]
[DATA0_H] [DATA0_L]  ...
```

### Fields

| Field | Size | Description |
| --- | --- | --- |
| `'w'` | 1 byte | Write-block opcode |
| Address | 2 bytes | Word address (big-endian) |
| Length | 2 bytes | Number of **words** |
| Data | 2 \* length bytes | Raw 16-bit words |

Example: Writing 32 words starting at address `0x0200`:

```
77 02 00 00 20 [data...]
```

### Device → Host Response

```
'K'   # success
```

Any other response indicates failure.

* * *

4\. Read Block Command (`r`)
============================

### Host → Device Frame

```
'r'
[ADDR_H] [ADDR_L]
[LEN_H]  [LEN_L]
```

### Device → Host Response

Returns `LEN * 2` bytes exactly:

```
[DATA0_H] [DATA0_L] ...
```

If the Arduino returns fewer bytes or nothing, the read is treated as a failure.

* * *

5\. Disconnect (`x`)
====================

### Host → Device

```
'x'
```

Arduino should flush buffers and reset its internal state.

* * *

6\. Memory Model
================

The PC side treats the PIC memory map as **word-addressed (16-bit)**.

*   All addresses in the protocol represent **word offsets**, not byte offsets.
*   Intel HEX records are divided by 2 during load (`address // 2`).
*   High address records (type 4) are shifted accordingly.

### Flash write sizes

Determined by:

```
FLASH_WRITE = <hex value>  # number of words
```

Chunks are padded with `0x3FFF`, matching erased PIC flash.

* * *

7\. Timing Requirements (Firmware-Side)
=======================================

The host assumes:

*   Device will respond within **5 seconds** to any command.
*   Write-block commands may require flash erase/write cycles, but must still return within timeout.
*   The Arduino firmware should **not** send unsolicited data.

* * *

8\. Verification Logic
======================

After writing each block:

1.  Host issues a read (`r`)
2.  Compares byte-for-byte
3.  Reports first mismatch position if any

Config words are handled separately and may be outside flash write boundaries.

* * *

9\. Dry-Run Behavior
====================

When `--dry-run` is used:

*   No serial port is opened.
*   All reads return `0x3FFF` words.
*   All writes succeed instantly.
*   Output still shows block-by-block activity.
