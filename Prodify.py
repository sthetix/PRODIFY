import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
import winsound
import os
import hashlib
import sys
import struct
import shutil

# Version check
SCRIPT_VERSION = "1.0.1"
print(f"Running Prodify version {SCRIPT_VERSION}")

# Determine if the application is a script file or frozen exe
if getattr(sys, 'frozen', False):
    script_dir = sys._MEIPASS
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))

icon_path = os.path.join(script_dir, 'icon.png')
warning_icon_path = os.path.join(script_dir, 'icon.png')
left_joycon_path = os.path.join(script_dir, 'images', 'left.png')
right_joycon_path = os.path.join(script_dir, 'images', 'right.png')

# Constants from NX_Wifi_Region_Changer 
CRC_16_TABLE = [
    0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
    0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400
]
DEBUG_MODE = True

def load_images():
    try:
        left_joycon_photo = tk.PhotoImage(file=left_joycon_path)
        right_joycon_photo = tk.PhotoImage(file=right_joycon_path)
        left_joycon_label.config(image=left_joycon_photo)
        right_joycon_label.config(image=right_joycon_photo)
        left_joycon_label.image = left_joycon_photo
        right_joycon_label.image = right_joycon_photo
    except Exception as e:
        print(f"Error loading images: {e}")

def get_crc_16(data):
    crc = 0x55AA
    for byte in data:
        r = CRC_16_TABLE[crc & 0x0F]
        crc = ((crc >> 4) & 0x0FFF) ^ r ^ CRC_16_TABLE[byte & 0x0F]
        r = CRC_16_TABLE[crc & 0x0F]
        crc = ((crc >> 4) & 0x0FFF) ^ r ^ CRC_16_TABLE[(byte >> 4) & 0x0F]
    return crc

def parse_header(file_path):
    with open(file_path, "r+b") as file:
        header = file.read(0x40)
        file_size = os.path.getsize(file_path)
        if file_size >= 0x4210 and DEBUG_MODE:
            file.seek(0x3FC0)
            rsa_block = file.read(0x250)
            print(f"Rsa2048DeviceCertificateBlock (0x3FC0-0x420F): {rsa_block.hex().upper()[:64]}...")
        if DEBUG_MODE:
            print(f"Raw header (0x00-0x3F): {header.hex().upper()}")
        try:
            magic, version, body_size, model, update_count, pad, crc, body_hash = struct.unpack("<IIIHH14sH32s", header)
            if magic != 0x304C4143:
                raise ValueError("Invalid CAL0 magic")
            computed_crc = get_crc_16(header[:0x1E])
            if computed_crc != crc:
                raise ValueError(f"Header CRC-16 mismatch: computed {computed_crc:04X}, stored {crc:04X}")
            if DEBUG_MODE:
                print(f"Parsed header: magic={magic:08X}, version={version}, body_size={body_size}, model={model}, update_count={update_count}, crc={crc:04X}")
            return body_size, body_hash
        except (struct.error, ValueError) as e:
            if DEBUG_MODE:
                print(f"Header parsing failed: {e}. Using fallback body_size 32704")
            return 32704, None

def compute_sha256(file_path, offset=0x40):
    with open(file_path, "rb") as file:
        file_size = os.path.getsize(file_path)
        try:
            body_size, _ = parse_header(file_path)
        except ValueError as e:
            if DEBUG_MODE:
                print(f"Error in compute_sha256: {e}. Using fallback body_size 32704.")
            body_size = 32704
        if body_size + offset > file_size:
            body_size = file_size - offset
        file.seek(offset)
        data = file.read(body_size)
        if len(data) != body_size:
            raise ValueError(f"Failed to read {body_size} bytes from offset 0x{offset:04X}")
        computed_hash = hashlib.sha256(data).digest()
    if DEBUG_MODE:
        print(f"Computed SHA-256 (offset 0x{offset:04X}, size={body_size} bytes): {computed_hash.hex().upper()}")
    return computed_hash

def is_valid_prodinfo(file_path):
    if not os.path.exists(file_path):
        show_warning("File Error", "PRODINFO file not found.")
        return False
    file_size = os.path.getsize(file_path)
    with open(file_path, "rb") as file:
        magic = file.read(4)
        if magic != b"CAL0":
            show_warning("File Error", "PRODINFO is invalid or encrypted.")
            return False
        try:
            body_size, _ = parse_header(file_path)
            if DEBUG_MODE:
                print(f"Validation passed: File size={file_size}, CAL0 magic={magic.hex()}, body_size={body_size}")
        except ValueError as e:
            if DEBUG_MODE:
                print(f"Validation warning: Failed to validate header: {e}.")
        return True

def calculate_and_update_crc(color_key):
    color_hex = color_entries[color_key].get().lstrip('#').upper()
    if len(color_hex) != 6 or not all(c in "0123456789ABCDEF" for c in color_hex):
        checksum_entries[color_key].set("----")
        return
    color_bytes = bytes.fromhex(color_hex)
    padded_data = list(color_bytes) + [0xFF] + [0x00] * 10
    crc_value = get_crc_16(padded_data)
    crc_hex = format(crc_value, '04X')
    checksum_entries[color_key].set(crc_hex)
    status_label.config(text=f"{color_key} CRC-16: {crc_hex}")
    update_color_rectangles()

def update_color(color_key):
    color_code = colorchooser.askcolor(title=f"Choose {color_key}")
    if color_code:
        rgb_color = color_code[0]
        hex_color = ''.join([f'{int(c):02X}' for c in rgb_color]).upper()
        color_entries[color_key].set(hex_color)
        color_cards[color_key].config(bg='#' + hex_color)
        calculate_and_update_crc(color_key)
        update_color_rectangles()

def limit_hex_input(color_key, *args):
    hex_value = color_entries[color_key].get().upper()
    if len(hex_value) > 6:
        show_warning("Input Error", "HEX code exceeds 6 characters.")
        color_entries[color_key].set(hex_value[:6])
    elif len(hex_value) == 6:
        if all(c in "0123456789ABCDEF" for c in hex_value):
            color_code = f"#{hex_value}"
            color_cards[color_key].config(bg=color_code)
            calculate_and_update_crc(color_key)
        else:
            show_warning("Input Error", "Invalid HEX code.")
    update_color_rectangles()

def update_color_rectangles():
    body_color = color_entries['Main Color'].get().lstrip('#').upper()
    bezel_color = color_entries['Bezel Color'].get().lstrip('#').upper()
    if len(body_color) == 6 and len(bezel_color) == 6 and all(c in "0123456789ABCDEF" for c in body_color + bezel_color):
        body_color = f"#{body_color}"
        bezel_color = f"#{bezel_color}"
        canvas.itemconfig(body_rectangle, outline=body_color)
        canvas.itemconfig(bezel_rectangle, outline=bezel_color)
    else:
        canvas.itemconfig(body_rectangle, outline="#000000")
        canvas.itemconfig(bezel_rectangle, outline="#000000")

def limit_input_length(*args):
    value = input_var.get()
    if len(value) > 14:
        show_warning("Input Error", "Serial exceeds 14 characters.")
        input_var.set(value[:14])
    if value and not all(32 <= ord(c) <= 126 for c in value):
        show_warning("Input Error", "Invalid ASCII characters.")
        input_var.set(''.join(c for c in value if 32 <= ord(c) <= 126))

def open_prodinfo():
    global prodinfo_file_path, original_serial, original_colors
    prodinfo_file_path = filedialog.askopenfilename(
        title="Open PRODINFO File",
        filetypes=[("PRODINFO Files", "*.bin *.dec PRODINFO"), ("All Files", "*.*")]
    )
    if not prodinfo_file_path:
        status_label.config(text="No file selected.")
        return
    if not is_valid_prodinfo(prodinfo_file_path):
        status_label.config(text="Invalid PRODINFO file.")
        return
    if not os.access(prodinfo_file_path, os.W_OK):
        show_warning("File Error", "PRODINFO file is read-only.")
        return
    shutil.copy(prodinfo_file_path, prodinfo_file_path + ".bak")
    try:
        with open(prodinfo_file_path, "rb") as file:
            if DEBUG_MODE:
                print(f"Loading PRODINFO: {prodinfo_file_path}, size: {os.path.getsize(prodinfo_file_path)} bytes")
            file.seek(0x250)
            data = file.read(0xE)
            ascii_text = data.decode('ascii', errors='replace')
            prodinfo_text.config(state=tk.NORMAL)
            prodinfo_text.delete(1.0, tk.END)
            prodinfo_text.insert(tk.END, ascii_text)
            prodinfo_text.config(state=tk.DISABLED)
            original_serial = ascii_text.strip()
            input_var.set(original_serial)
            extract_colors(file)
            file_name_value_label.config(text=os.path.basename(prodinfo_file_path))
            status_label.config(text="PRODINFO loaded.")
            if DEBUG_MODE:
                file.seek(0x0)
                full_block = file.read(0x1F40)
                full_block_crc = get_crc_16(full_block)
                file.seek(0x40)
                invalid_block = file.read(0x1F00)
                invalid_block_crc = get_crc_16(invalid_block)
                file.seek(0x0)
                backup_block = file.read(0x8000)
                backup_block_crc = get_crc_16(backup_block)
                file.seek(0x1F40)
                checksum_1f40 = file.read(4)
                file.seek(0x1F3C)
                checksum_1f3c = file.read(4)
                file.seek(0x8000)
                checksum_8000 = file.read(4) if os.path.getsize(prodinfo_file_path) >= 0x8004 else b""
                print(f"Full block (0x0-0x1F3F): CRC-16: {full_block_crc:04X}")
                print(f"Invalid block (0x40-0x1F3F): CRC-16: {invalid_block_crc:04X}")
                print(f"Backup block (0x0-0x7FFF): CRC-16: {backup_block_crc:04X}")
                print(f"Stored checksum at 0x1F40-0x1F43: {checksum_1f40.hex().upper()}")
                print(f"Stored checksum at 0x1F3C-0x1F3F: {checksum_1f3c.hex().upper()}")
                print(f"Stored checksum at 0x8000-0x8003: {checksum_8000.hex().upper()}")
    except Exception as e:
        show_error("File Error", "Failed to load PRODINFO.")
        status_label.config(text="Failed to load PRODINFO.")
        if DEBUG_MODE:
            print(f"Error loading PRODINFO: {e}")

def extract_colors(file):
    global color_cards, original_colors
    color_blocks = {
        'Bezel Color': 0x4230,
        'Main Color': 0x4240,
    }
    original_colors = {}
    for key, offset in color_blocks.items():
        file.seek(offset)
        color_bytes = file.read(3)
        file.seek(offset + 14)
        checksum_bytes = file.read(2)
        color_hex = color_bytes.hex().upper()
        checksum_hex = format(int.from_bytes(checksum_bytes, byteorder="little"), '04X')
        color_entries[key].set(color_hex)
        color_cards[key].config(bg='#' + color_hex)
        checksum_entries[key].set(checksum_hex)
        original_colors[key] = color_hex
        if DEBUG_MODE:
            file.seek(offset)
            block_data = file.read(14)
            computed_crc = get_crc_16(block_data[:14])
            stored_crc = int.from_bytes(checksum_bytes, byteorder="little")
            print(f"{key} block (0x{offset:04X}-0x{offset+13:04X}): {block_data.hex().upper()}")
            print(f"{key} stored CRC-16: {stored_crc:04X}, computed: {computed_crc:04X}")
    update_color_rectangles()

def update_prodinfo():
    if DEBUG_MODE:
        print("Entering update_prodinfo()")
    if not prodinfo_file_path:
        show_warning("File Error", "No PRODINFO file selected.")
        return
    try:
        changes_made = False
        input_ascii = entry_input.get().strip()
        if DEBUG_MODE:
            print(f"Serial input: '{input_ascii}', original_serial: '{original_serial}'")
            print(f"File writable: {os.access(prodinfo_file_path, os.W_OK)}")
        if input_ascii != original_serial:
            changes_made = True
        for key in offsets:
            current_color = color_entries[key].get().lstrip('#').upper()
            if current_color != original_colors[key]:
                changes_made = True
                if DEBUG_MODE:
                    print(f"Color change detected for {key}: {original_colors[key]} -> {current_color}")
        if not changes_made:
            show_info("No Changes", "No changes made.")
            if DEBUG_MODE:
                print("No changes detected, exiting update_prodinfo")
            return
        with open(prodinfo_file_path, 'r+b') as file:
            file.seek(0x10)
            update_count = int.from_bytes(file.read(2), byteorder="little")
            update_count += 1
            file.seek(0x10)
            file.write(update_count.to_bytes(2, byteorder="little"))
            file.flush()
            os.fsync(file.fileno())
            if DEBUG_MODE:
                print(f"Updated header update_count to {update_count}")
            file.seek(0)
            header_data = file.read(0x1E)
            header_crc = get_crc_16(header_data)
            file.seek(0x1E)
            file.write(header_crc.to_bytes(2, byteorder="little"))
            file.flush()
            os.fsync(file.fileno())
            if DEBUG_MODE:
                print(f"Updated header CRC-16 to {header_crc:04X}")
            if DEBUG_MODE:
                file.seek(0x250)
                pre_serial_data = file.read(30)
                print(f"Pre-update SerialNumberBlock (0x250-0x26D): {pre_serial_data.hex().upper()}")
            if len(input_ascii) != 14:
                show_warning("Serial Error", "Serial must be 14 characters.")
                if DEBUG_MODE:
                    print("Serial length invalid, exiting update_prodinfo")
                return
            if not all(32 <= ord(c) <= 126 for c in input_ascii):
                show_warning("Serial Error", "Invalid ASCII characters.")
                if DEBUG_MODE:
                    print("Serial contains invalid ASCII, exiting update_prodinfo")
                return
            input_bytes = input_ascii.encode('ascii')
            middle_string = [0x00] * 16
            data_with_middle = input_bytes + bytes(middle_string)
            crc_result = get_crc_16(data_with_middle)
            crc_bytes = crc_result.to_bytes(2, byteorder="little")
            final_data = data_with_middle + crc_bytes
            if DEBUG_MODE:
                print(f"Serial data (0x250-0x26D): {final_data.hex().upper()}")
                print(f"Computed serial CRC-16: {crc_result:04X}")
            file.seek(0x250)
            file.write(final_data)
            file.flush()
            os.fsync(file.fileno())
            if DEBUG_MODE:
                file.seek(0x250)
                post_write_data = file.read(30)
                post_write_crc = int.from_bytes(post_write_data[28:30], byteorder="little")
                print(f"Post-write SerialNumberBlock (0x250-0x26D): {post_write_data.hex().upper()}")
                print(f"Post-write serial CRC-16: {post_write_crc:04X}")
                if post_write_crc != crc_result:
                    print("Warning: Serial CRC-16 write verification failed!")
            for key, offset in offsets.items():
                current_color = color_entries[key].get().lstrip('#').upper()
                if current_color != original_colors[key]:
                    if len(current_color) != 6 or not all(c in "0123456789ABCDEF" for c in current_color):
                        show_warning("Color Error", f"Invalid {key} HEX code.")
                        if DEBUG_MODE:
                            print(f"Invalid color for {key}: {current_color}, exiting update_prodinfo")
                        return
                    color_bytes = bytes.fromhex(current_color)
                    padded_data = list(color_bytes) + [0xFF] + [0x00] * 10
                    crc_value = get_crc_16(padded_data)
                    crc_bytes = crc_value.to_bytes(2, byteorder="little")
                    file.seek(offset)
                    file.write(color_bytes + b'\xFF' + b'\x00' * 10 + crc_bytes)
                    file.flush()
                    os.fsync(file.fileno())
                    if DEBUG_MODE:
                        file.seek(offset)
                        block_data = file.read(14)
                        computed_crc = get_crc_16(block_data)
                        file.seek(offset + 14)
                        stored_crc = int.from_bytes(file.read(2), byteorder="little")
                        print(f"{key} updated block (0x{offset:04X}-0x{offset+13:04X}): {block_data.hex().upper()}")
                        print(f"{key} CRC-16 stored: {stored_crc:04X}, computed: {computed_crc:04X}")
            new_sha256 = compute_sha256(prodinfo_file_path, offset=0x40)
            file.seek(0x20)
            file.write(new_sha256)
            file.flush()
            os.fsync(file.fileno())
            if DEBUG_MODE:
                file.seek(0x20)
                stored_sha256 = file.read(32)
                print(f"Updated SHA-256 at 0x20: {stored_sha256.hex().upper()}")
                if stored_sha256 != new_sha256:
                    print("Warning: SHA-256 write verification failed!")
            file.seek(0x0)
            full_block_data = file.read(0x8000)
            full_block_crc = get_crc_16(full_block_data)
            file.seek(0x8000)
            file.write(full_block_crc.to_bytes(2, byteorder="little") + b'\x00\x00')
            file.flush()
            os.fsync(file.fileno())
            if DEBUG_MODE:
                print(f"Updated block CRC-16 for 0x0-0x7FFF at 0x8000: {full_block_crc:04X}")
            if DEBUG_MODE:
                file.seek(0x0)
                full_block = file.read(0x1F40)
                full_block_crc = get_crc_16(full_block)
                file.seek(0x40)
                invalid_block = file.read(0x1F00)
                invalid_block_crc = get_crc_16(invalid_block)
                file.seek(0x0)
                backup_block = file.read(0x8000)
                backup_block_crc = get_crc_16(backup_block)
                file.seek(0x1F40)
                checksum_1f40 = file.read(4)
                file.seek(0x1F3C)
                checksum_1f3c = file.read(4)
                file.seek(0x8000)
                checksum_8000 = file.read(4)
                print(f"Post-update Full block (0x0-0x1F3F): CRC-16: {full_block_crc:04X}")
                print(f"Post-update Invalid block (0x40-0x1F3F): CRC-16: {invalid_block_crc:04X}")
                print(f"Post-update Backup block (0x0-0x7FFF): CRC-16: {backup_block_crc:04X}")
                print(f"Post-update checksum at 0x1F40-0x1F43: {checksum_1f40.hex().upper()}")
                print(f"Post-update checksum at 0x1F3C-0x1F3F: {checksum_1f3c.hex().upper()}")
                print(f"Post-update checksum at 0x8000-0x8003: {checksum_8000.hex().upper()}")
        show_info("Success", "PRODINFO updated.")
        status_label.config(text="PRODINFO updated.")
        if DEBUG_MODE:
            print("Exiting update_prodinfo: PRODINFO updated successfully")
    except Exception as e:
        show_error("File Error", "Update failed.")
        status_label.config(text="Update failed.")
        if DEBUG_MODE:
            print(f"Exiting update_prodinfo: Error - {e}")

def show_info(title, message):
    create_popup(title, message, "info")

def show_error(title, message):
    create_popup(title, message, "error")

def show_warning(title, message):
    create_popup(title, message, "warning")

def create_popup(title, message, type):
    popup = tk.Toplevel(root)
    popup.title(title)
    popup.geometry(center_popup(popup))
    try:
        popup.iconphoto(True, tk.PhotoImage(file=warning_icon_path))
    except Exception as e:
        print(f"Warning icon not found at {warning_icon_path}: {e}")
    label = tk.Label(popup, text=message, wraplength=300)
    label.pack(pady=10, padx=10)
    button_frame = tk.Frame(popup)
    button_frame.pack(pady=5)
    winsound.MessageBeep(winsound.MB_ICONASTERISK)
    ok_button = tk.Button(button_frame, text="OK", command=popup.destroy)
    ok_button.pack()

def center_popup(popup):
    root.update_idletasks()
    width = 300
    height = 100
    x = root.winfo_x() + (root.winfo_width() // 2) - (width // 2)
    y = root.winfo_y() + (root.winfo_height() // 2) - (height // 2)
    return f"{width}x{height}+{x}+{y}"

root = tk.Tk()
root.title(f"PRODIFY - The PRODINFO Editor v{SCRIPT_VERSION}")
root.geometry("400x350")
try:
    root.iconphoto(True, tk.PhotoImage(file=icon_path))
except Exception as e:
    messagebox.showwarning("Icon Not Found", f"Icon file not found: {icon_path}")
root.resizable(False, False)

status_label = tk.Label(root, text="", anchor='center')
status_label.grid(row=11, column=0, columnspan=3, pady=(5, 0))

offsets = {
    'Bezel Color': 0x4230,
    'Main Color': 0x4240,
}

color_cards = {}
color_entries = {}
checksum_entries = {}
original_colors = {}

input_frame = tk.Frame(root)
input_frame.grid(row=0, column=0, columnspan=3, pady=10)

input_var = tk.StringVar()
input_var.trace("w", limit_input_length)

prodinfo_label = tk.Label(input_frame, text="Current Serial Number ")
prodinfo_label.grid(row=0, column=0, padx=(0, 0), pady=5, sticky=tk.W)
prodinfo_text = tk.Text(input_frame, bg="white", width=30, height=1, state=tk.DISABLED)
prodinfo_text.grid(row=0, column=1, padx=(0, 5), pady=5, sticky=tk.W)

tk.Label(input_frame, text="New Serial Number ").grid(row=1, column=0, padx=(0, 0), pady=5, sticky=tk.W)
entry_input = tk.Entry(input_frame, textvariable=input_var, width=40)
entry_input.grid(row=1, column=1, padx=(0, 5), pady=5, sticky=tk.W)

bezel_color_label = tk.Label(input_frame, text="Bezel Color")
bezel_color_label.grid(row=2, column=0, padx=(0, 0), pady=5, sticky=tk.W)
bezel_color_entry = tk.StringVar()
color_entries['Bezel Color'] = bezel_color_entry
bezel_color_input = tk.Entry(input_frame, textvariable=bezel_color_entry, width=30)
bezel_color_input.grid(row=2, column=1, padx=(0, 5), pady=5, sticky=tk.W)
bezel_color_entry.trace("w", lambda *args: limit_hex_input('Bezel Color'))

main_color_label = tk.Label(input_frame, text="Main Color")
main_color_label.grid(row=3, column=0, padx=(0, 0), pady=5, sticky=tk.W)
main_color_entry = tk.StringVar()
color_entries['Main Color'] = main_color_entry
main_color_input = tk.Entry(input_frame, textvariable=main_color_entry, width=30)
main_color_input.grid(row=3, column=1, padx=(0, 5), pady=5, sticky=tk.W)
main_color_entry.trace("w", lambda *args: limit_hex_input('Main Color'))

color_frame = tk.Frame(input_frame)
color_frame.grid(row=2, column=1, rowspan=2, padx=(0, 0), pady=5, sticky=tk.E)

for idx, label in enumerate(offsets.keys()):
    color_card = tk.Label(color_frame, width=5, height=1, bg="white", relief="solid")
    color_card.grid(row=idx, column=0, padx=(5, 5), pady=5, sticky=tk.W)
    color_card.bind("<Button-1>", lambda e, key=label: update_color(key))
    color_cards[label] = color_card
    checksum_entry = tk.StringVar()
    checksum_entries[label] = checksum_entry
    checksum_display = tk.Entry(color_frame, textvariable=checksum_entry, width=6, state='readonly')
    checksum_display.grid(row=idx, column=1, padx=(3, 3), pady=0, sticky=tk.W)
    checksum_display.grid_remove()

# Place "Opened File" label and value in input_frame to align with input fields
file_name_label = tk.Label(input_frame, text="Opened File:")
file_name_label.grid(row=4, column=0, padx=(0, 0), pady=5, sticky=tk.W)
file_name_value_label = tk.Label(input_frame, text="", anchor='w')
file_name_value_label.grid(row=4, column=1, padx=(0, 5), pady=5, sticky=tk.W)

joycon_frame = tk.Frame(root)
joycon_frame.grid(row=8, column=0, columnspan=3)

left_joycon_label = tk.Label(joycon_frame)
left_joycon_label.grid(row=0, column=0, padx=(20, 20), pady=(10, 0))

canvas = tk.Canvas(joycon_frame, width=150, height=80, bg="#f0f0f0")
canvas.grid(row=0, column=1, padx=(0, 0), pady=(10, 0))

body_rectangle = canvas.create_rectangle(10, 8, 140, 75, outline="#000000", width=8)
bezel_rectangle = canvas.create_rectangle(14, 13, 136, 70, outline="#000000", width=5)

right_joycon_label = tk.Label(joycon_frame)
right_joycon_label.grid(row=0, column=2, padx=(20, 20), pady=(10, 0))

load_images()

btn_frame = tk.Frame(root)
btn_frame.grid(row=9, column=0, columnspan=3, pady=(5, 0))

btn_load = tk.Button(btn_frame, text="Load PRODINFO", command=open_prodinfo)
btn_load.grid(row=0, column=0, padx=(95, 5), pady=(5, 0))

btn_update = tk.Button(btn_frame, text="Update PRODINFO", command=update_prodinfo)
btn_update.grid(row=0, column=1, padx=(5, 95), pady=(5, 0))

root.mainloop()