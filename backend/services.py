"""Safe upstream errors and small, bounded, process-local caches."""
import copy
import threading
import time
from collections import OrderedDict
import requests


class ServiceError(Exception):
    def __init__(self, message, status=502, *, upstream_status=None, retry_after=None, reason=None):
        super().__init__(message)
        self.status = status
        self.upstream_status = upstream_status
        self.retry_after = retry_after
        self.reason = reason


class TTLCache:
    def __init__(self, ttl=60, capacity=128):
        self.ttl, self.capacity = ttl, capacity
        self.data = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            item = self.data.get(key)
            if item and item[0] > time.monotonic():
                self.data.move_to_end(key)
                return copy.deepcopy(item[1])
            self.data.pop(key, None)
        return None

    def put(self, key, value):
        with self.lock:
            self.data[key] = (time.monotonic() + self.ttl, copy.deepcopy(value))
            self.data.move_to_end(key)
            while len(self.data) > self.capacity:
                self.data.popitem(last=False)

    def clear(self):
        with self.lock:
            self.data.clear()


def request_json(method, url, *, service, attempts=2, allowed_status=(), **kwargs):
    """Never propagate request URLs, response bodies, or credentials to callers."""
    for attempt in range(attempts):
        try:
            response = getattr(requests, method)(url, **kwargs)
            if response.status_code in (401, 403):
                raise ServiceError(f'{service} rejected its configured credentials or permissions.', 503, upstream_status=response.status_code, reason='credentials')
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(0.25 * (2 ** attempt))
                continue
            if not response.ok and response.status_code not in allowed_status:
                raise ServiceError(f'{service} returned HTTP {response.status_code}.', upstream_status=response.status_code, retry_after=response.headers.get('Retry-After'), reason='http')
            data = response.json()
            if not isinstance(data, dict):
                raise ServiceError(f'{service} returned an invalid response.')
            return data
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2 ** attempt))
                continue
            raise ServiceError(f'{service} timed out or could not be reached.', 504, reason='timeout' if isinstance(error, requests.Timeout) else 'connection') from None
        except (requests.RequestException, ValueError):
            raise ServiceError(f'{service} returned an invalid response.') from None
    raise ServiceError(f'{service} is unavailable.')
