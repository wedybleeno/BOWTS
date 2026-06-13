import socket
import threading
import ipaddress
import os
import PySimpleGUI as sg
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# --- Configuration ---
PORT = 9090
PASSWORD = os.getenv('CLIENT_PASSWORD', '1234')
TIMEOUT = 1  # seconds

# Global variables
found_server_ip = None
client_socket = None
current_path = ''

# Helper functions

def get_my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def scan_ip(ip):
    global found_server_ip
    if found_server_ip:
        return
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((ip, PORT))
        found_server_ip = ip
        s.close()
    except:
        pass


def send_command(cmd):
    """
    Sends a command and returns cleaned output without prompts.
    """
    try:
        client_socket.send(cmd.encode('utf-8'))
        data = client_socket.recv(65536).decode('utf-8', errors='replace')
        # Remove any [Shell] prompts and blank lines
        lines = [line for line in data.splitlines() if line.strip() and not line.strip().startswith('[Shell]')]
        return '\n'.join(lines)
    except Exception as e:
        return f"[-] Error: {e}"

# GUI Layout
sg.theme('DarkBlue3')
drives_combo = sg.Combo(values=[], key='-DRIVES-', size=(8,1), enable_events=True, readonly=True)
controls = [sg.Button('Connect'), sg.Button('Disconnect'), sg.Text('   '), sg.Button('Up'), sg.Button('Refresh'), drives_combo]
file_listbox = sg.Listbox(values=[], key='-FILES-', size=(60,15), enable_events=True)
file_content = sg.Multiline('', size=(60,10), key='-CONTENT-', disabled=True, autoscroll=True)
ops = [sg.Button('Open'), sg.Button('View File'), sg.Button('Delete File'), sg.Button('Create File')]
layout = [
    [sg.Text('Remote File Explorer', font=('Arial', 16))],
    controls,
    [file_listbox, file_content],
    ops,
    [sg.Output(size=(80,5), key='-LOG-')]
]

window = sg.Window('Remote Explorer', layout, finalize=True)

# Event loop
while True:
    event, values = window.read()
    if event in (sg.WINDOW_CLOSED, 'Disconnect'):
        if client_socket:
            client_socket.close()
        break

    if event == 'Connect':
        window['-LOG-'].print("[~] Scanning local network...")
        my_ip = get_my_ip()
        network = ipaddress.ip_network(my_ip + '/24', strict=False)
        threads = [threading.Thread(target=scan_ip, args=(str(ip),)) for ip in network.hosts()]
        for t in threads: t.start()
        for t in threads: t.join()
        if not found_server_ip:
            window['-LOG-'].print("[-] Server not found.")
            continue
        window['-LOG-'].print(f"[+] Server: {found_server_ip}")
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((found_server_ip, PORT))
        client_socket.send(PASSWORD.encode('utf-8'))
        resp = client_socket.recv(1024).decode('utf-8', errors='replace')
        window['-LOG-'].print(resp)
        # Populate drives via fsutil
        out = send_command('fsutil fsinfo drives')
        # out example: 'Drives: C:\ D:\ W:\'
        if 'Drives:' in out:
            parts = out.split(':', 1)[1].split()
            drives = [p[0] for p in parts]
        else:
            drives = []
        window['-DRIVES-'].update(values=drives)
        if drives:
            window['-DRIVES-'].update(value=drives[0])
            window.write_event_value('-DRIVES-', drives[0])

    if event == '-DRIVES-' and client_socket:
        drive = values['-DRIVES-']
        if drive:
            current_path = f"{drive}:\\"
            out_dirs = send_command(f'dir "{current_path}" /b /ad')
            out_files = send_command(f'dir "{current_path}" /b /a-d')
            dirs = out_dirs.splitlines() if out_dirs else []
            files = out_files.splitlines() if out_files else []
            entries = [f"[D] {d}" for d in dirs] + [f"[F] {f}" for f in files]
            window['-FILES-'].update(values=entries)
            window['-CONTENT-'].update('')
            window['-LOG-'].print(f"Listing {current_path}")

    if event == 'Refresh' and client_socket and current_path:
        # same as drive selection
        window.write_event_value('-DRIVES-', values['-DRIVES-'])

    if event == 'Up' and client_socket and current_path:
        current_path = os.path.dirname(current_path.rstrip('\\')) + '\\'
        window.write_event_value('-DRIVES-', current_path[0])

    if event == 'Open' and client_socket and values['-FILES-']:
        sel = values['-FILES-'][0]
        if sel.startswith('[D] '):
            folder = sel[4:]
            current_path = os.path.join(current_path, folder) + '\\'
            window.write_event_value('-DRIVES-', current_path[0])

    if event == 'View File' and client_socket and values['-FILES-']:
        sel = values['-FILES-'][0]
        if sel.startswith('[F] '):
            fname = sel[4:]
            content = send_command(f'type "{current_path}{fname}"')
            window['-CONTENT-'].update(content)
            window['-LOG-'].print(f"Loaded {fname}")

    if event == 'Delete File' and client_socket and values['-FILES-']:
        sel = values['-FILES-'][0]
        if sel.startswith('[F] '):
            fname = sel[4:]
            resp = send_command(f'del "{current_path}{fname}"')
            window['-LOG-'].print(resp)
            window.write_event_value('Refresh', None)

    if event == 'Create File' and client_socket and current_path:
        fname = sg.popup_get_text('New file name')
        if fname:
            resp = send_command(f'type nul > "{current_path}{fname}"')
            window['-LOG-'].print(resp)
            window.write_event_value('Refresh', None)

window.close()
