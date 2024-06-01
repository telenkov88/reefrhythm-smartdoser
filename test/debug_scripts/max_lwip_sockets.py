import uasyncio as asyncio

MAX_CONN = 5
tcp_opened = 0


async def handle_client(reader, writer):
    global tcp_opened
    tcp_opened += 1
    port = writer.get_extra_info('peername')[1]
    print("Accepted connection on port {}. Connections open: {}".format(port, tcp_opened))

    try:
        while True:
            message = "Hello from port {}, Connection opened: {}".format(port, tcp_opened)
            await writer.awrite(message)
            await asyncio.sleep(5)
    finally:
        tcp_opened -= 1
        print("Closing connection on port {}. Connections open: {}".format(port, tcp_opened))
        await writer.aclose()


async def run_server(port):
    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    print("Server running on port {}".format(port))
    while True:
        await asyncio.sleep(3600)  # Keep the server task alive indefinitely


async def main():
    tasks = [run_server(port) for port in range(10000, 10000 + MAX_CONN)]
    await asyncio.gather(*tasks)  # Run all server tasks concurrently

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Stopped by user")

