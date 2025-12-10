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
    The final bytes are serialized in Big Endian order for serial transmission.
    Returns a dict: {start_address: bytes_data}
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


class ArduinoProgrammer:
    def __init__(self, port, baud=115200, dry_run=False):
        self.dry_run = dry_run
        self.port = port
        self.baud = baud
        self.ser = None

    def connect(self):
        if self.dry_run:
            print(f"[DRY RUN] Pretending to connect to {self.port}...", end=' ')
            print("Success.")
            return True

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=5)
            print("Connecting...", end=' ', flush=True)
            time.sleep(2) 
            self.ser.write(b's')
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


def verify_chunks(prog, chunks, memory_type):
    """Verifies a set of memory chunks against the device."""
    verify_error = False
    print(f"Verifying {len(chunks)} {memory_type} blocks...")
    
    for addr, expected_data in sorted(chunks.items()):
        word_count = len(expected_data) // 2
        print(f"Verifying 0x{addr:04X} ({memory_type})...", end=' ')
        
        actual_data = prog.read_block(addr, word_count)
        
        if actual_data is None:
            print("READ FAIL (No response)")
            verify_error = True
            break
        
        if actual_data != expected_data:
            print(f"FAIL: Expected {expected_data.hex()}, got {actual_data.hex()}")
            verify_error = True
            for i in range(min(len(expected_data), len(actual_data))):
                if expected_data[i] != actual_data[i]:
                    print(f"  Mismatch at byte {i}: Expected 0x{expected_data[i]:02X}, Got 0x{actual_data[i]:02X}")
                    break
            break
        
        print("OK")
    
    return not verify_error

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('hexfile', nargs='?', help='Input Intel HEX file for flashing or verifying.')
    parser.add_argument('-d', '--device', required=True, help='Path to pic_devices.ini.')
    parser.add_argument('-p', '--port', required=True, help='Serial Port.')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without hardware.')
    parser.add_argument('-c', '--config', action='store_true', help='Also include config words (applies to -f and -v).')

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-f', '--flash', action='store_true', help='Write hexfile to device flash memory.')
    group.add_argument('-v', '--verify', action='store_true', help='Verify hexfile against device memory.')
    group.add_argument('-w', '--write-word', nargs=2, metavar=('ADDR', 'HEXWORD'), help='Write a single 16-bit word to an address (e.g., -w 0x0010 0x8131).')
    group.add_argument('-r', '--read-word', nargs=1, metavar=('ADDR'), help='Read a single 16-bit word from an address (e.g., -r 0x0010).')
    group.add_argument('--dump', nargs=2, metavar=('ADDR', 'LEN'), help='Read a block of memory and display it (e.g., --dump 0x0000 128).')
    
    args = parser.parse_args()

    cfg = configparser.ConfigParser(strict=False)
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
        print(f"Error: Multiple devices found in {args.device}. Please ensure the config only contains one device section.")
        print(f"Available devices: {', '.join(available_devices)}")
        sys.exit(1)

    device_cfg = cfg[mcu_id]
    flash_write_size = int(device_cfg.get('FLASH_WRITE', '20'), 16)
    
    config_mem_start = 0xFFFF
    config_mem_end = 0xFFFF
    rom_size = int(device_cfg.get('ROMSIZE', '0'), 16)

    config_range_str = device_cfg.get('CONFIG')
    if config_range_str:
        try:
            start, end = [int(x.strip(), 16) for x in config_range_str.split('-')]
            config_mem_start = start
            config_mem_end = end
        except ValueError:
            print("Warning: Invalid 'CONFIG' range format in INI file.")

    print(f"Device: {mcu_id} | Row Size: {flash_write_size} words | Config Range: 0x{config_mem_start:X}-0x{config_mem_end:X} | Dry Run: {args.dry_run}")

    prog = ArduinoProgrammer(args.port, dry_run=args.dry_run)
    if not prog.connect():
        sys.exit(1)

    try:
        def verify_chunks(prog, chunks, memory_type):
            """Verifies a set of memory chunks against the device."""
            verify_error = False
            print(f"Verifying {len(chunks)} {memory_type} blocks...")
            
            for addr, expected_data in sorted(chunks.items()):
                word_count = len(expected_data) // 2
                print(f"Verifying 0x{addr:04X} ({memory_type})...", end=' ')
                
                actual_data = prog.read_block(addr, word_count)
                
                if actual_data is None:
                    print("READ FAIL (No response)")
                    verify_error = True
                    break
                
                if actual_data != expected_data:
                    print(f"FAIL: Expected {expected_data.hex()}, got {actual_data.hex()}")
                    verify_error = True
                    break
                
                print("OK")
            
            return not verify_error

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
                
        elif args.verify and args.hexfile:
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

        elif args.dump:
            addr, length = int(args.dump[0], 16), int(args.dump[1])
            data = prog.read_block(addr, length)
            
            if data is None:
                print("Dump Read Failed (No response)")
            else:
                print(f"--- DUMP: 0x{addr:04X} to 0x{addr + length - 1:04X} ({length} words) ---")
                current_addr = addr
                for i in range(0, len(data), 16):
                    line_data = data[i:i+16]
                    
                    hex_string = ' '.join([f'{w:04X}' for w in [
                        int.from_bytes(line_data[j:j+2], 'big') for j in range(0, len(line_data), 2)
                    ]])
                    
                    print(f"0x{current_addr:04X}: {hex_string}")
                    current_addr += len(line_data) // 2


        elif args.read_word:
            addr = int(args.read_word[0], 16)
            data = prog.read_block(addr, 1)
            
            if data is None:
                print(f"Read 0x{addr:04X} Failed")
            else:
                word_val = int.from_bytes(data, 'big')
                print(f"Read 0x{addr:04X}: 0x{word_val:04X}")

        elif args.write_word:
            addr = int(args.write_word[0], 16)
            word_val = int(args.write_word[1], 16)
            data = word_val.to_bytes(2, 'big')
            
            print(f"Writing {data.hex()} to 0x{addr:04X}...", end=' ')
            if prog.write_block(addr, data):
                if args.dry_run:
                    print("Success (Simulated)")
                else:
                    print("Success")
                    v = prog.read_block(addr, 1)
                    print("Verify Match" if v == data else f"Verify Mismatch: {v.hex()}")
            else:
                print("Write Failed")

    finally:
        prog.disconnect()

if __name__ == '__main__':
    main()