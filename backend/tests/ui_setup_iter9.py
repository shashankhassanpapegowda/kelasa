"""Helper: put Ravi on duty and outside zone (fresh unacknowledged alert). Prints employee token."""
import sys
import requests
from conftest import BASE_URL, TINY_JPEG_B64

r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "emp1.test@gtgroups.local", "password": "RaviReset@26"})
tok = r.json()["session_token"]
h = {"Authorization": f"Bearer {tok}"}
body = {"lat": 12.9720, "lng": 77.5946, "accuracy": 10, "descriptor": [0.01] * 128, "image_b64": TINY_JPEG_B64}
mode = sys.argv[1] if len(sys.argv) > 1 else "setup"
if mode == "setup":
    print("checkin", requests.post(f"{BASE_URL}/api/attendance/checkin", json=body, headers=h).status_code)
    requests.post(f"{BASE_URL}/api/location/ping", json={"lat": 12.9720, "lng": 77.5946, "accuracy": 10}, headers=h)
    print("ping out", requests.post(f"{BASE_URL}/api/location/ping", json={"lat": 12.99, "lng": 77.5946, "accuracy": 10}, headers=h).text)
elif mode == "checkout":
    print("checkout", requests.post(f"{BASE_URL}/api/attendance/checkout", json=body, headers=h).text)
print("TOKEN", tok)
