import socket
import threading
import ipaddress
from colorama import Fore, Style
import os
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

PORT = 9090
PASSWORD = os.getenv('CLIENT_PASSWORD', '1234')  # тот же пароль, что на сервере
TIMEOUT = 1  # секунды

found_server_ip = None

def get_my_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # не обязательно реально подключаться
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

def auto_find_server():
    my_ip = get_my_ip()
    network = ipaddress.ip_network(my_ip + '/24', strict=False)
    threads = []

    print(Fore.CYAN + f"[~] Поиск сервера в сети {network}..." + Style.RESET_ALL)

    for ip in network.hosts():
        t = threading.Thread(target=scan_ip, args=(str(ip),))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if not found_server_ip:
        print(Fore.RED + "[-] Сервер не найден в сети." + Style.RESET_ALL)
        exit()

    print(Fore.GREEN + f"[+] Найден сервер на IP: {found_server_ip}" + Style.RESET_ALL)

def start_connection():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.connect((found_server_ip, PORT))

    # Отправка пароля
    client_socket.send(PASSWORD.encode())
    auth_response = client_socket.recv(1024).decode()
    print(Fore.YELLOW + auth_response + Style.RESET_ALL)

    if "Неверный пароль" in auth_response:
        client_socket.close()
        exit()

    try:
        while True:
            server_message = client_socket.recv(4096).decode()
            command = input(server_message)
            client_socket.send(command.encode())

            if command.lower() in ('exit', 'quit'):
                break

            result = client_socket.recv(65536).decode()
            print(result)

    except KeyboardInterrupt:
        print("\nОтключение...")
        client_socket.close()

if __name__ == "__main__":
    auto_find_server()
    start_connection()
