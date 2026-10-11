"""One explicit live /resources request; optional second request verifies the cache."""
import argparse
import time
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--latitude', type=float, default=40.7681)
    parser.add_argument('--longitude', type=float, default=-73.9819)
    parser.add_argument('--radius', type=int, default=500)
    parser.add_argument('--repeat-cache', action='store_true')
    args = parser.parse_args()
    params = {'latitude': args.latitude, 'longitude': args.longitude, 'radius': args.radius}
    previous = None
    for index in range(2 if args.repeat_cache else 1):
        started = time.monotonic()
        try:
            response = requests.get(args.base_url.rstrip('/') + '/resources', params=params, timeout=60)
            data = response.json()
        except (requests.RequestException, ValueError) as error:
            print(f'FAIL: {type(error).__name__}; check the local API/network.')
            return 1
        print(f'Request {index + 1}: HTTP {response.status_code}, {time.monotonic() - started:.2f}s')
        if not response.ok:
            # ServiceError messages contain only safe endpoint hostnames/status categories.
            print(data.get('detail', 'API request failed.'))
            return 1
        if not isinstance(data, list):
            print('FAIL: expected a facility list.')
            return 1
        print(f"PASS: {len(data)} real mapped facilities; categories: {sorted({f['type'] for f in data})}")
        if previous is not None and previous != data:
            print('FAIL: repeated response changed within the cache window.')
            return 1
        previous = data
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
