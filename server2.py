import socket
import subprocess
import os
from colorama import Fore, Style
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

HOST = '0.0.0.0'    # слушать на всех интерфейсах
PORT = 9090         # порт должен совпадать с клиентом
PASSWORD = os.getenv('CLIENT_PASSWORD', '1234')   # пароль той же, что и в клиенте

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
    except Exception as e:
        print(Fore.RED + f"[-] Ошибка привязки сокета: {e}" + Style.RESET_ALL)
        return

    server_socket.listen(5)
    print(Fore.GREEN + f"[+] Сервер запущен на {HOST}:{PORT}, ожидаем подключения..." + Style.RESET_ALL)

    while True:
        conn, addr = server_socket.accept()
        print(Fore.CYAN + f"[+] Подключение установлено от {addr}" + Style.RESET_ALL)
        try:
            handle_client(conn)
        except Exception as e:
            print(Fore.RED + f"[-] Ошибка в работе с клиентом: {e}" + Style.RESET_ALL)
        finally:
            conn.close()
            print(Fore.YELLOW + f"[~] Соединение с {addr} закрыто." + Style.RESET_ALL)

def handle_client(conn):
    # 1) Авторизация
    recv_password = conn.recv(1024).decode('utf-8').strip()
    if recv_password != PASSWORD:
        conn.send("[-] Неверный пароль. Отключение.\n".encode('utf-8'))
        return
    conn.send("[+] Авторизация успешна.\n".encode('utf-8'))

    # 2) Консольный цикл
    while True:
        conn.send("\n[Shell]$ ".encode('utf-8'))
        command = conn.recv(4096).decode('utf-8').strip()
        if not command:
            break

        # Выход
        if command.lower() in ('exit', 'quit'):
            conn.send("[~] Завершение соединения.\n".encode('utf-8'))
            break

        # Смена папки
        if command.startswith('cd '):
            try:
                os.chdir(command[3:])
                conn.send(f"[+] Переход в каталог {os.getcwd()}\n".encode('utf-8'))
            except Exception as e:
                conn.send(f"[-] Ошибка перехода каталога: {e}\n".encode('utf-8'))
            continue

        # Выполнение любой другой команды через shell
        try:
            output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            output = e.output
        except Exception as e:
            output = str(e).encode('utf-8')

        # Если нет вывода — сообщаем об успешном выполнении
        if not output.strip():
            output = "[+] Команда выполнена успешно (без вывода).\n".encode('utf-8')

        conn.send(output)

if __name__ == "__main__":
    main()
