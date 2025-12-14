#!/usr/bin/env python3
import sys
import time
import argparse
import configparser
import serial
import os
from typing import Dict

def int_to_bytes(number, length=2):
    return number.to_bytes(length, 'big')

def chunk_data(data_dict, chunk_size):
    """
    Groups individual words into chunks of exactly chunk_size.
    Pads with 0x3FFF (typical empty PIC flash value).
    Returns a dict: {start_address: bytes_data (Big Endian for Serial)}
    """
    chunks = {}
    for addr in sorted(data_dict.keys()):
        base_addr = addr - (addr % chunk_size)
        offset = addr - base_addr
        
        if base_addr not in chunks:
            chunks[base_addr] = [0x3FFF] * chunk_size
            
        chunks[base_addr][offset] = data_dict[addr]

    final_chunks = {}
    for addr, words in chunks.items():
        b_array = bytearray()
        for w in words:
            b_array.extend(w.to_bytes(2, 'big'))
        final_chunks[addr] = bytes(b_array)
    return final_chunks

def load_hex(path: str, hex_byte_order: str = 'little') -> Dict[int, int]:
    """
    Loads an Intel HEX file and returns the memory map dictionary 
    {word_address: int_value} using a fixed word size of 2 bytes (16-bit).
    """
    WORD_SIZE = 2
    words: Dict[int, int] = {}
    high_address_offset: int = 0
    
    try:
        with open(path, 'r') as f:
            hexfile_data = f.read().replace('\n', '').replace('\r', '')
        
        ascii_records = hexfile_data.lstrip(':').split(':')

        for record in ascii_records:
            if not record: 
                continue
            
            try:
                data_len = int(record[0:2], base=16) 
                offset_addr = int(record[2:6], base=16)
                record_type = int(record[6:8], base=16)
                
                end_data_idx = (data_len * 2) + 8
                data_bytes = bytearray.fromhex(record[8:end_data_idx]) 
            except ValueError:
                continue

            if record_type == 4 and data_len == 2:
                high_address = int.from_bytes(data_bytes, 'big')
                high_address_offset = (high_address << 16) // WORD_SIZE
            
            elif record_type == 0:
                current_low_address = offset_addr // WORD_SIZE
                
                for i in range(0, data_len, WORD_SIZE):
                    address = high_address_offset + current_low_address
                    word = int.from_bytes(data_bytes[i : i + WORD_SIZE], hex_byte_order)
                    words[address] = word
                    current_low_address += 1

        return words
        
    except FileNotFoundError:
        print(f"Error: File not found at path: {path}")
        return {}
    except Exception as e:
        print(f"An error occurred during decoding: {e}")
        return {}

def save_hex(path: str, data_dict: Dict[int, int]):
    """
    Saves a memory dictionary {word_address: int_value} to an Intel HEX file.
    Converts 16-bit word addresses to byte addresses and handles Extended Linear Address records.
    """
    try:
        with open(path, 'w') as f:
            sorted_addrs = sorted(data_dict.keys())
            if not sorted_addrs:
                return

            current_high_addr = 0
            
            line_data = bytearray()
            line_start_addr = -1
            
            def write_record(address, record_type, data):
                count = len(data)
                checksum = count + (address >> 8) + (address & 0xFF) + record_type + sum(data)
                checksum = (~checksum + 1) & 0xFF
                hex_str = f":{count:02X}{address:04X}{record_type:02X}{data.hex().upper()}{checksum:02X}\n"
                f.write(hex_str)

            for i, word_addr in enumerate(sorted_addrs):
                byte_addr = word_addr * 2
                
                high_addr = byte_addr >> 16
                low_addr = byte_addr & 0xFFFF
                
                if high_addr != current_high_addr:
                    if line_data:
                        write_record(line_start_addr, 0x00, line_data)
                        line_data = bytearray()
                    
                    high_bytes = high_addr.to_bytes(2, 'big')
                    write_record(0x0000, 0x04, high_bytes)
                    current_high_addr = high_addr

                if (line_start_addr == -1) or \
                   (low_addr != line_start_addr + len(line_data)) or \
                   (len(line_data) >= 16):
                    
                    if line_data:
                        write_record(line_start_addr, 0x00, line_data)
                    
                    line_start_addr = low_addr
                    line_data = bytearray()

                word_val = data_dict[word_addr]
                line_data.extend(word_val.to_bytes(2, 'little'))

            if line_data:
                write_record(line_start_addr, 0x00, line_data)

            write_record(0x0000, 0x01, b'')
            
        print(f"Saved {len(data_dict)} words to {path}")

    except Exception as e:
        print(f"Error saving hex file: {e}")

class ArduinoProgrammer:
    def __init__(self, port, baud=115200, dry_run=False):
        self.dry_run = dry_run
        self.port = port
        self.baud = baud
        self.ser = None

    def connect(self, lvp=False):
        command_byte = b'l' if lvp else b's'
        mode_name = "LVP" if lvp else "HVP"

        if self.dry_run:
            print(f"[DRY RUN] Pretending to connect ({mode_name}) to {self.port}...", end=' ')
            print("Success.")
            return True

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=5)
            print(f"Connecting ({mode_name})...", end=' ', flush=True)
            time.sleep(2) 
            self.ser.write(command_byte)
            if self.ser.read() == b'K':
                print("Success.")
                return True
            print("Failed (No 'K' response).")
            return False
        except Exception as e:
            print(f"Connection Error: {e}")
            return False

    def disconnect(self):
        if self.dry_run:
            print("[DRY RUN] Disconnected.")
            return
        
        if self.ser and self.ser.is_open:
            self.ser.write(b'x')
            self.ser.flush()
            self.ser.close()

    def write_block(self, addr, data_bytes):
        if self.dry_run:
            return True

        self.ser.write(b'w')
        self.ser.write(int_to_bytes(addr))
        self.ser.write(int_to_bytes(len(data_bytes)//2))
        self.ser.write(data_bytes)
        return self.ser.read() == b'K'

    def read_block(self, addr, word_count):
        if self.dry_run:
            return b'\x3F\xFF' * word_count

        self.ser.write(b'r')
        self.ser.write(int_to_bytes(addr))
        self.ser.write(int_to_bytes(word_count))
        resp = self.ser.read(word_count * 2)
        return resp if len(resp) == word_count * 2 else None
    
    def erase_row(self, addr):
        if self.dry_run:
            return True
        self.ser.write(b'e') 
        self.ser.write(int_to_bytes(addr))
        resp = self.ser.read()
        return resp == b'K'
    
    def bulk_erase(self, addr):
        if self.dry_run:
            return True
        self.ser.write(b'b') 
        self.ser.write(int_to_bytes(addr))
        resp = self.ser.read()
        return resp == b'K'


def main():
    parser = argparse.ArgumentParser(description="Arduino-based PIC Programmer Client")
    parser.add_argument('hexfile', nargs='?', help='Input Intel HEX file for flashing or verifying.')
    parser.add_argument('-d', '--device', required=False, help='Path to pic_devices.ini (Required for Flash, Verify, and Full Dump).')
    parser.add_argument('-p', '--port', required=True, help='Serial Port.')
    parser.add_argument('--lvp', action='store_true', help='Use Low-Voltage Programming (LVP) mode instead of High-Voltage Programming (HVP).')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without hardware.')
    parser.add_argument('-c', '--config', action='store_true', help='Also include config words (applies to -f and -v).')
    parser.add_argument('-f', '--flash', action='store_true', help='Write hexfile to device flash memory.')
    parser.add_argument('-v', '--verify', action='store_true', help='Verify hexfile against device memory.')
    parser.add_argument('--wipe', action='store_true', help='Erase ENTIRE Flash memory.')
    parser.add_argument('-w', '--write', nargs=2, metavar=('ADDR', 'HEX_DATA'), help='Write a block of bytes (e.g., -w 0x0010 8131FFEE).')
    parser.add_argument('-e', '--erase-row', nargs=1, metavar=('ADDR'), help='Erase a single row of flash memory (e.g., -e 0x0400).')
    parser.add_argument('-r', '--read', nargs=2, metavar=('ADDR', 'LEN'), help='Read a block of memory and display it (e.g., -r 0x0000 128).')
    parser.add_argument('--dump', nargs=1, metavar=('FILENAME'), help='Dump entire Flash and Config to a .HEX file (Requires -d).')
    
    args = parser.parse_args()

    cfg = configparser.ConfigParser(strict=False)
    mcu_id = "Unknown"
    flash_write_size = 32
    rom_size = 0
    config_mem_start = 0
    config_mem_end = 0
    device_loaded = False

    if args.device:
        if not os.path.exists(args.device):
            print(f"Error: Config file not found at {args.device}")
            sys.exit(1)
            
        cfg.read(args.device)
        available_devices = cfg.sections()
        
        if len(available_devices) == 0:
            print(f"Error: No device sections found in {args.device}.")
            sys.exit(1)
        elif len(available_devices) == 1:
            mcu_id = available_devices[0]
            print(f"Auto-detecting device: {mcu_id}")
        else:
            print(f"Error: Multiple devices found in {args.device}.")
            sys.exit(1)

        device_cfg = cfg[mcu_id]
        flash_write_size = int(device_cfg.get('FLASH_WRITE', '20'), 16)
        rom_size = int(device_cfg.get('ROMSIZE', '0'), 16)
        config_range_str = device_cfg.get('CONFIG')
        if config_range_str:
            try:
                start, end = [int(x.strip(), 16) for x in config_range_str.split('-')]
                config_mem_start = start
                config_mem_end = end
            except ValueError:
                pass
        device_loaded = True

        print(f"Device: {mcu_id} | Row Size: {flash_write_size} words | Config Range: 0x{config_mem_start:X}-0x{config_mem_end:X}")
    
    if (args.flash or args.verify or args.dump) and not device_loaded:
        print("Error: The --device (-d) argument is REQUIRED for Flash, Verify, and Full Dump operations.")
        sys.exit(1)

    print(f"Dry Run: {args.dry_run}")

    prog = ArduinoProgrammer(args.port, dry_run=args.dry_run)
    if not prog.connect(lvp=args.lvp):
        sys.exit(1)

    try:
        if args.wipe:
            print(f"WIPING Device Flash Memory...", end=' ')
            if not prog.bulk_erase(int("0x80FF", 16)):
                print(" FAIL")
            print("OK.")
        
        if args.flash and args.hexfile:
            raw_data = load_hex(args.hexfile)
            flash_data = {}
            config_data = {}
            for addr, word in raw_data.items():
                if config_mem_start <= addr <= config_mem_end:
                    config_data[addr] = word
                elif addr < rom_size:
                    flash_data[addr] = word
            
            flash_chunks = chunk_data(flash_data, flash_write_size)
            print(f"Flashing {len(flash_chunks)} program blocks...")
            
            flash_error = False
            for addr, data in sorted(flash_chunks.items()):
                print(f"Writing 0x{addr:04X}...", end=' ')
                if not prog.write_block(addr, data):
                    print("WRITE FAIL")
                    flash_error = True
                    break
                if args.dry_run:
                    print("OK (Simulated)")
                else:
                    verify_data = prog.read_block(addr, len(data)//2)
                    if verify_data != data:
                        print(f"VERIFY FAIL at 0x{addr:04X} expected {data.hex()}, got {verify_data.hex()}")
                        flash_error = True
                        break
                    print("OK")
            
            if flash_error:
                print("FLASHING FAILED.")
            elif args.config and config_data:
                print(f"Writing {len(config_data)} Configuration words...")
                config_write_chunks = {}
                for addr, word in sorted(config_data.items()):
                    config_write_chunks[addr] = word.to_bytes(2, 'big') 

                config_ok = True
                for addr, data in sorted(config_write_chunks.items()):
                    print(f"Writing Config 0x{addr:04X}...", end=' ')
                    if not prog.write_block(addr, data):
                        print("CONFIG WRITE FAIL")
                        config_ok = False
                        break
                    
                    if args.dry_run:
                        print("OK (Simulated)")
                    else:
                        verify_data = prog.read_block(addr, 1)
                        if verify_data != data:
                            print(f"CONFIG VERIFY FAIL at 0x{addr:04X} expected {data.hex()}, got {verify_data.hex()}")
                            config_ok = False
                            break
                        print("OK")
                
                if config_ok:
                    print("FLASH & VERIFY COMPLETE: SUCCESS")
                else:
                    print("FLASH & VERIFY COMPLETE: FAILED")
            elif not flash_error:
                print("FLASH COMPLETE: SUCCESS")

        if args.verify and args.hexfile:
            def verify_chunks(prog, chunks, memory_type):
                verify_error = False
                print(f"Verifying {len(chunks)} {memory_type} blocks...")
                for addr, expected_data in sorted(chunks.items()):
                    word_count = len(expected_data) // 2
                    print(f"Verifying 0x{addr:04X} ({memory_type})...", end=' ')
                    actual_data = prog.read_block(addr, word_count)
                    if actual_data is None:
                        print("READ FAIL")
                        verify_error = True
                        break
                    if actual_data != expected_data:
                        print(f"FAIL: Expected {expected_data.hex()}, got {actual_data.hex()}")
                        verify_error = True
                        break
                    print("OK")
                return not verify_error

            raw_data = load_hex(args.hexfile)
            flash_data = {}
            config_data = {}
            for addr, word in raw_data.items():
                if config_mem_start <= addr <= config_mem_end:
                    config_data[addr] = word
                elif addr < rom_size:
                    flash_data[addr] = word

            flash_chunks = chunk_data(flash_data, flash_write_size)
            flash_ok = verify_chunks(prog, flash_chunks, "Program Flash")
            
            config_ok = True
            if config_data:
                config_chunks = {}
                for addr, word in sorted(config_data.items()):
                    config_chunks[addr] = word.to_bytes(2, 'big')
                config_ok = verify_chunks(prog, config_chunks, "Configuration")
                
            if flash_ok and config_ok:
                print("VERIFY COMPLETE: SUCCESS")
            else:
                print("VERIFY COMPLETE: FAILED")

        if args.erase_row:
            addr = int(args.erase_row[0], 16)
            print(f"Erasing row at 0x{addr:04X}...", end=' ')
            if prog.erase_row(addr):
                print("Success")
            else:
                print("Erase Failed")

        if args.write:
            addr = int(args.write[0], 16)
            hex_data_str = args.write[1]
            
            try:
                data = bytes.fromhex(hex_data_str)
            except ValueError:
                print(f"Error: Invalid hex data string provided: {hex_data_str}")
                sys.exit(1)
            
            if len(data) % 2 != 0:
                print("Error: HEX_DATA must represent an even number of bytes (16-bit words).")
                sys.exit(1)
            
            print(f"Writing {data.hex()} ({len(data)//2} words) to 0x{addr:04X}...", end=' ')
            if prog.write_block(addr, data):
                if args.dry_run:
                    print("Success (Simulated)")
                else:
                    print("Success")
                    v = prog.read_block(addr, len(data) // 2)
                    print("Verify Match" if v == data else f"Verify Mismatch: {v.hex()}")
            else:
                print("Write Failed")
                
        if args.read:
            addr, length = int(args.read[0], 16), int(args.read[1])
            print(f"Reading {length} words from 0x{addr:04X}...")
            
            CHUNK_SIZE = 64
            current_addr = addr
            remaining = length
            
            while remaining > 0:
                fetch_len = min(remaining, CHUNK_SIZE)
                data = prog.read_block(current_addr, fetch_len)
                
                if data is None:
                    print(f"Read Failed at 0x{current_addr:04X}")
                    break
                
                for i in range(0, len(data), 16):
                    line_data = data[i:i+16]
                    hex_string = ' '.join([f'{w:04X}' for w in [
                        int.from_bytes(line_data[j:j+2], 'big') for j in range(0, len(line_data), 2)
                    ]])
                    print(f"0x{current_addr:04X}: {hex_string}")
                    current_addr += len(line_data) // 2
                
                remaining -= fetch_len
                
        if args.dump:
            filename = args.dump[0]
            print(f"Dumping Flash (0x0000 - 0x{rom_size:04X}) and Config to {filename}...")
            
            dump_data = {}
            
            read_chunk = 64
            for addr in range(0, rom_size, read_chunk):
                count = min(read_chunk, rom_size - addr)
                print(f"\rReading Flash 0x{addr:04X}...", end='')
                
                block_bytes = prog.read_block(addr, count)
                if block_bytes:
                    for i in range(0, len(block_bytes), 2):
                        word_val = int.from_bytes(block_bytes[i:i+2], 'big')
                        dump_data[addr + (i//2)] = word_val
                else:
                    print(f" Error reading 0x{addr:04X}")

            print("\nReading Config...", end=' ')
            if config_mem_start > 0 and config_mem_end >= config_mem_start:
                cfg_len = (config_mem_end - config_mem_start) + 1
                cfg_bytes = prog.read_block(config_mem_start, cfg_len)
                if cfg_bytes:
                    for i in range(0, len(cfg_bytes), 2):
                        word_val = int.from_bytes(cfg_bytes[i:i+2], 'big')
                        dump_data[config_mem_start + (i//2)] = word_val
                    print("Done.")
                else:
                    print("Failed.")
            else:
                print("Skipped.")

            print("Filtering empty memory (0x3FFF)...")
            filtered_dump = {}
            for addr, val in dump_data.items():
                is_config = (config_mem_start <= addr <= config_mem_end)
                if val != 0x3FFF or is_config:
                    filtered_dump[addr] = val
            
            print(f"Saving to {filename}...")
            save_hex(filename, filtered_dump)
            print(f"Done. (Filtered {len(dump_data) - len(filtered_dump)} empty words)")



    finally:
        prog.disconnect()

if __name__ == '__main__':
    main()
