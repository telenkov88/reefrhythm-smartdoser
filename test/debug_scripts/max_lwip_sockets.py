import uasyncio as asyncio
import gc

MAX_CONN = 32
tcp_opened = 0
long_buffer = "a" * 1024 * 128


async def handle_client(reader, writer):
    global tcp_opened
    tcp_opened += 1
    port = writer.get_extra_info('peername')[1]
    print("Accepted connection on port {}. Connections open: {}".format(port, tcp_opened))

    try:

        while True:
            message = "Hello from port {}, Connection opened: {}\r\n".format(port, tcp_opened)
            try:
                await writer.awrite(message)
                await writer.awrite(long_buffer)
            except Exception as e:
                print("Connection closed, ", e)
                return
            print(gc.mem_free())
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
    gc.collect()
    asyncio.run(main())
except KeyboardInterrupt:
    print("Stopped by user")
