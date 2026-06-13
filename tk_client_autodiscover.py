import socket
import threading
import ipaddress
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

class RemoteFileExplorer:
    def __init__(self, master):
        self.master = master
        master.title("Удаленное управление системой")
        master.geometry("1000x700")

        # Настройки подключения
        self.PORT = 9090
        self.PASSWORD = os.getenv('CLIENT_PASSWORD', '1234')
        self.client = None
        self.server_ip = None
        # empty means showing drives
        self.current_path = ''

        # Построение интерфейса
        self.build_ui()

    def build_ui(self):
        # Верхняя панель
        top = ttk.Frame(self.master, padding=5)
        top.pack(fill=tk.X)
        self.connect_btn = ttk.Button(top, text="Connect", command=self.start_scan)
        self.connect_btn.pack(side=tk.LEFT, padx=5)
        self.disconnect_btn = ttk.Button(top, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.disconnect_btn.pack(side=tk.LEFT, padx=5)

        # Статус
        status = ttk.Frame(self.master)
        status.pack(fill=tk.X)
        ttk.Label(status, text="Статус:").pack(side=tk.LEFT)
        self.status_label = ttk.Label(status, text="Ожидание подключения...")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Панель разделения
        pane = ttk.PanedWindow(self.master, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, pady=5)

        # Список
        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        self.file_list = tk.Listbox(left, exportselection=False)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.file_list.bind('<Double-1>', lambda e: self.open_selected())
        scroll = ttk.Scrollbar(left, command=self.file_list.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_list.config(yscrollcommand=scroll.set)

        # Превью
        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        self.preview = tk.Text(right, state=tk.DISABLED, wrap=tk.WORD)
        self.preview.pack(fill=tk.BOTH, expand=True)
        ps = ttk.Scrollbar(right, command=self.preview.yview)
        ps.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview.config(yscrollcommand=ps.set)

        # Кнопки действий
        btns = ttk.Frame(self.master)
        btns.pack(fill=tk.X, pady=5)
        actions = [
            ("Show PC", self.show_disks),
            ("List", self.list_files),
            ("Up", self.go_up),
            ("Cwd", self.show_path),
            ("Download", self.download_file),
            ("Delete", self.delete_file),
            ("Mkdir", self.mkdir),
            ("System", self.system_info)
        ]
        self.buttons = []
        for text, cmd in actions:
            b = ttk.Button(btns, text=text, command=cmd, state=tk.DISABLED)
            b.pack(side=tk.LEFT, padx=3)
            self.buttons.append(b)

    def start_scan(self):
        self.connect_btn.config(state=tk.DISABLED)
        threading.Thread(target=self.auto_connect, daemon=True).start()

    def auto_connect(self):
        # Сначала localhost и локальный IP
        self.update_status("Connecting to localhost...")
        for host in ['127.0.0.1', self.get_ip()]:
            try:
                s = socket.socket()
                s.settimeout(0.5)
                s.connect((host, self.PORT))
                s.send(self.PASSWORD.encode('utf-8'))
                res = s.recv(1024).decode('utf-8', errors='ignore')
                if "Авторизация успешна" in res:
                    self.client = s
                    self.server_ip = host
                    self.on_connect(res)
                    return
                s.close()
            except:
                pass
        # Сканирование сети
        self.update_status("Scanning local network...")
        local = self.get_ip()
        net = ipaddress.ip_network(local + '/24', strict=False)
        for ip in net.hosts():
            if self.client:
                break
            try:
                s = socket.socket()
                s.settimeout(0.5)
                s.connect((str(ip), self.PORT))
                s.send(self.PASSWORD.encode('utf-8'))
                res = s.recv(1024).decode('utf-8', errors='ignore')
                if "Авторизация успешна" in res:
                    self.client = s
                    self.server_ip = str(ip)
                    self.on_connect(res)
                    return
                s.close()
            except:
                pass
        # Не найдено
        self.update_status("Server not found")
        self.connect_btn.config(state=tk.NORMAL)

    def on_connect(self, msg):
        self.update_status(f"Connected to {self.server_ip}")
        self.connect_btn.config(state=tk.DISABLED)
        self.disconnect_btn.config(state=tk.NORMAL)
        for b in self.buttons:
            b.config(state=tk.NORMAL)
        threading.Thread(target=self.recv_loop, daemon=True).start()
        # Сразу показать диски
        self.show_disks()
        self.append_text(msg)

    def recv_loop(self):
        while True:
            try:
                data = self.client.recv(65536)
                if not data:
                    break
                text = data.decode('utf-8', errors='replace')
                self.append_text(text)
            except:
                break
        self.update_status("Disconnected")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        for b in self.buttons:
            b.config(state=tk.DISABLED)

    def disconnect(self):
        if self.client:
            try:
                self.client.close()
            except:
                pass
        self.client = None
        self.update_status("Disconnected")
        self.connect_btn.config(state=tk.NORMAL)
        self.disconnect_btn.config(state=tk.DISABLED)
        for b in self.buttons:
            b.config(state=tk.DISABLED)

    def send(self, cmd):
        if not self.client:
            return
        if cmd.lower().startswith('cd '):
            self.current_path = cmd[3:].strip().strip('"')
        try:
            self.client.send(cmd.encode('utf-8'))
        except:
            pass

    def update_status(self, txt):
        self.master.after(0, lambda: self.status_label.config(text=txt))

    def append_text(self, msg):
        self.preview.config(state=tk.NORMAL)
        self.preview.delete('1.0', tk.END)
        self.preview.insert(tk.END, msg)
        self.preview.config(state=tk.DISABLED)

    # Навигация по дискам
    def show_disks(self):
        self.current_path = ''
        self.send('fsutil fsinfo drives')
        self.master.after(200, self.populate_disks)

    def populate_disks(self):
        content = self.preview.get('1.0', tk.END).strip().splitlines()
        self.file_list.delete(0, tk.END)
        for line in content:
            if line.lower().startswith('drives:'):
                parts = line.split(':',1)[1].split()
                for d in parts:
                    drive = d.rstrip('\\')
                    self.file_list.insert(tk.END, f"[D] {drive}")
                break

    # Файловые операции
    def list_files(self):
        # если нет пути, показываем диски
        if not self.current_path:
            return self.show_disks()
        # нормализуем
        path = self.current_path
        if not path.endswith('\\'):
            path += '\\'
        self.send(f'dir "{path}" /b')
        self.master.after(200, self.populate_list)

    def populate_list(self):
        content = self.preview.get('1.0', tk.END).strip().splitlines()
        self.file_list.delete(0, tk.END)
        for line in content:
            if not line:
                continue
            full = os.path.join(self.current_path, line)
            if os.path.isdir(full):
                self.file_list.insert(tk.END, f"[D] {line}")
            else:
                self.file_list.insert(tk.END, f"[F] {line}")

    def open_selected(self):
        sel = self.file_list.get(tk.ACTIVE)
        if not sel:
            return
        kind, name = sel.split(' ', 1)
        if kind == '[D]':
            # диск или папка
            if len(name) == 1 and name.isalpha():
                newpath = f"{name}:\\"
            else:
                newpath = os.path.join(self.current_path, name)
            self.current_path = newpath
            self.send(f'cd "{newpath}"')
            self.list_files()
        else:
            self.download_file()

    def go_up(self):
        if not self.current_path:
            return
        parent = os.path.dirname(self.current_path.rstrip('\\'))
        # если поднялись выше корня
        if len(parent) == 2 and parent[1] == ':' or not parent:
            self.show_disks()
        else:
            self.current_path = parent
            self.send(f'cd "{parent}"')
            self.list_files()

    def show_path(self):
        self.send('cd')

    def download_file(self):
        sel = self.file_list.get(tk.ACTIVE)
        if not sel or not sel.startswith('[F]'):
            return
        name = sel[4:]
        full = os.path.join(self.current_path, name)
        self.send(f'type "{full}"')
        def save():
            data = self.preview.get('1.0', tk.END)
            savepath = filedialog.asksaveasfilename(initialfile=name)
            if savepath:
                with open(savepath, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(data)
                messagebox.showinfo("Saved", f"{savepath} saved")
        self.master.after(300, save)

    def delete_file(self):
        sel = self.file_list.get(tk.ACTIVE)
        if not sel or not sel.startswith('[F]'):
            return
        name = sel[4:]
        full = os.path.join(self.current_path, name)
        if messagebox.askyesno("Delete", f"Delete {full}?"):
            self.send(f'del "{full}"')
            self.list_files()

    def mkdir(self):
        d = simpledialog.askstring("New folder", "Name:")
        if d:
            full = os.path.join(self.current_path, d)
            self.send(f'mkdir "{full}"')
            self.list_files()

    def system_info(self):
        for cmd in ["systeminfo", "whoami", "wmic logicaldisk get Caption,FreeSpace,Size"]:
            self.send(cmd)

    @staticmethod
    def get_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except:
            return '127.0.0.1'
        finally:
            s.close()

if __name__ == '__main__':
    root = tk.Tk()
    import tkinter.ttk as ttk
    RemoteFileExplorer(root)
    root.mainloop()
