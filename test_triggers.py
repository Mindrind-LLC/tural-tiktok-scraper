import asyncio
from playwright.async_api import async_playwright
from src.utils import parse_proxy_env

# List of proxies in the format user:pass@host:port
proxies = [
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10000",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10001",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10002",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10003",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10004",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10005",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10006",
    "9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10007",
]

async def main():
    async with async_playwright() as p:
        for proxy in proxies:
            userpass, hostport = proxy.split("@")
            username, password = userpass.split(":")
            server = hostport
            proxy_cfg = parse_proxy_env(proxy)

            print(f"\nLaunching browser with proxy {server} ...")

            browser = await p.chromium.launch(
                headless=False,
                # proxy={
                #     "server": f"http://{server}",
                #     "username": username,
                #     "password": password,
                # },
                proxy=proxy_cfg
            )
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://whatismyipaddress.com/")

            input("Press Enter to continue to the next proxy...")

            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
