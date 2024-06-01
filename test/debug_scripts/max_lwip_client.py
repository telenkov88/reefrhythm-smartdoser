import socket
import threading
import time


def client_thread(host, port):
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
                print(f"Connected to {host} on port {port}")

                while True:
                    data = s.recv(1024*128)
                    if not data:
                        print(f"Connection lost on port {port}. Attempting to reconnect...")
                        break  # Exit this loop to reconnect
                    print(f"Received from port {port}: {data.decode()}")

        except Exception as e:
            print(f"Error connecting to {host} on port {port}: {e}")
        print("Attempting to reconnect in 60 seconds...")
        time.sleep(60)


def start_clients(host, start_port, num_ports):
    threads = []
    for i in range(num_ports):
        port = start_port + i
        thread = threading.Thread(target=client_thread, args=(host, port))
        thread.start()
        threads.append(thread)
        time.sleep(0.1)  # slight delay to avoid burst of connections

    for thread in threads:
        thread.join()  # Wait for all threads to finish


if __name__ == "__main__":
    server_host = '192.168.254.146'  # Change to the IP address of your server
    starting_port = 10000
    number_of_ports = 32  # Number of consecutive ports to connect to

    start_clients(server_host, starting_port, number_of_ports)
