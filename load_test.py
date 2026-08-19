import asyncio
import sys

import httpx

BASE_URL = "http://127.0.0.1:8000"
CONCURRENCY = 300  # matches NFR1 in DESIGN.md: 200-500 concurrent requests


async def attempt_hold(client: httpx.AsyncClient, event_id: str, seat_id: str):
    try:
        resp = await client.post(f"{BASE_URL}/events/{event_id}/seats/{seat_id}/hold")
        return resp.status_code
    except Exception as e:
        return f"error: {e}"


async def main():
    if len(sys.argv) != 3:
        print("Usage: python3 load_test.py <event_id> <seat_id>")
        print("The seat must currently be 'available' - reseed if needed.")
        sys.exit(1)

    event_id, seat_id = sys.argv[1], sys.argv[2]

    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [attempt_hold(client, event_id, seat_id) for _ in range(CONCURRENCY)]
        results = await asyncio.gather(*tasks)

    success = results.count(200)
    conflict = results.count(409)
    other = len(results) - success - conflict

    print(f"Total requests fired:      {len(results)}")
    print(f"200 (won the seat):        {success}")
    print(f"409 (correctly rejected):  {conflict}")
    print(f"other/errors:              {other}")
    print()

    if success == 1:
        print("PASS - exactly one request won the seat under concurrent load. No double-booking.")
    else:
        print(f"FAIL - {success} requests succeeded. This should NEVER be more than 1.")


if __name__ == "__main__":
    asyncio.run(main())