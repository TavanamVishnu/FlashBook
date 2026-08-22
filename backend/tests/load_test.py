"""
Fires many simultaneous "hold this seat" requests at ONE seat and checks
the outcome. If the system is correct, exactly one request should win (200)
and every other request should be rejected (409) — never two winners, never
an unhandled error.

Usage (server must already be running, e.g. uvicorn app.main:app):

    python tests/load_test.py --requests 300 --seat-id 5 --email loadtest@example.com
"""
import argparse
import asyncio

import httpx

BASE_URL = "http://127.0.0.1:8000"


async def get_token(client: httpx.AsyncClient, email: str, password: str) -> str:
    resp = await client.post(f"{BASE_URL}/auth/signup", json={"email": email, "password": password})
    if resp.status_code == 409:
        resp = await client.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


async def fire_hold(client: httpx.AsyncClient, token: str, seat_id: int) -> int:
    try:
        resp = await client.post(
            f"{BASE_URL}/seats/{seat_id}/hold",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.status_code
    except Exception:
        return -1


async def main(total_requests: int, seat_id: int, email: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        token = await get_token(client, email, "loadtest-pass")

        # Make sure the seat starts out available for a clean test run.
        await client.post(f"{BASE_URL}/seats/{seat_id}/release", headers={"Authorization": f"Bearer {token}"})

        results = await asyncio.gather(*[fire_hold(client, token, seat_id) for _ in range(total_requests)])

    won = results.count(200)
    rejected = results.count(409)
    other = total_requests - won - rejected

    print(f"Total requests fired:      {total_requests}")
    print(f"200 (won the seat):        {won}")
    print(f"409 (correctly rejected):  {rejected}")
    print(f"other/errors:              {other}")
    print()
    if won == 1 and other == 0:
        print("PASS - exactly one request won the seat under concurrent load. No double-booking.")
    else:
        print("FAIL - double-booking or unexpected errors occurred.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--seat-id", type=int, required=True)
    parser.add_argument("--email", default="loadtest@example.com")
    args = parser.parse_args()

    asyncio.run(main(args.requests, args.seat_id, args.email))
