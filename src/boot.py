import time

try:
    from release_tag import *  # dinamically created in init.sh

    print("Extract app to flash")
    extart_start = time.time()
    # Application can be loaded from frozen module and written to flash.
    # For startup optimization we're rewriting app only if it's different from current version.
    with open("version.txt", "a+") as release:
        release_ver = release.read().rstrip()
    print(f"Current app version: {release_ver}, frozen app version: {RELEASE_TAG}")
    if RELEASE_TAG != release_ver:
        print("Rewrite app")
        import frozen_app

        with open("version.txt", "w") as release:
            release.write(RELEASE_TAG)
    print(f"Finished in {time.time() - extart_start}sec")
except ImportError:
    print("Skip on PC")


if __name__ == "__main__":
    from web import *
    asyncio.run(main())
