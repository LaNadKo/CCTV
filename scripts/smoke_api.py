#!/usr/bin/env python3
"""Basic end-to-end smoke test for the CCTV backend API."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


TINY_IMAGE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO6v99kAAAAASUVORK5CYII="


class SmokeError(RuntimeError):
    pass


@dataclass
class ApiClient:
    base_url: str
    token: str | None = None
    api_key: str | None = None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        expected: int | tuple[int, ...] = (200,),
        read_json: bool = True,
    ) -> Any:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            encoded = urllib.parse.urlencode(
                {k: v for k, v in query.items() if v is not None},
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"
        body = None
        headers = self._headers()
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
                if response.status not in (expected if isinstance(expected, tuple) else (expected,)):
                    raise SmokeError(f"{method} {path} returned unexpected status {response.status}")
                if not read_json:
                    return raw, response.headers
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.reason
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
                detail = payload.get("detail", detail)
            except Exception:
                pass
            raise SmokeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def _timestamp() -> str:
    return time.strftime("%Y%m%d%H%M%S")


def login_and_prepare_admin(client: ApiClient, login: str, password: str, new_password: str) -> str:
    result = client.request(
        "POST",
        "/auth/login",
        json_body={"login": login, "password": password},
    )
    token = result["access_token"]
    if result.get("must_change_password"):
        changer = ApiClient(client.base_url, token=token)
        changer.request(
            "POST",
            "/auth/change-password",
            json_body={"current_password": password, "new_password": new_password},
        )
        result = client.request(
            "POST",
            "/auth/login",
            json_body={"login": login, "password": new_password},
        )
        token = result["access_token"]
    return token


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test CCTV backend API")
    parser.add_argument("--base-url", default="http://192.168.50.62:8000")
    parser.add_argument("--admin-login", default="admin")
    parser.add_argument("--admin-password", default="admin")
    parser.add_argument("--new-admin-password", default="Admin12345!")
    parser.add_argument("--camera-stream-url", default="rtsp://example.invalid/stream1")
    parser.add_argument("--camera-ip", default="192.168.50.3")
    parser.add_argument("--keep-fixtures", action="store_true")
    args = parser.parse_args()

    anon = ApiClient(args.base_url)

    health = anon.request("GET", "/health")
    _assert(health.get("status") == "ok", "health endpoint did not return ok")
    print("[ok] /health")

    token = None
    login_error = None
    for candidate in (args.admin_password, args.new_admin_password):
        try:
            token = login_and_prepare_admin(anon, args.admin_login, candidate, args.new_admin_password)
            break
        except Exception as exc:
            login_error = exc
    if not token:
        raise SmokeError(f"admin login failed: {login_error}")

    admin = ApiClient(args.base_url, token=token)
    me = admin.request("GET", "/auth/me")
    _assert(me["login"] == args.admin_login, "unexpected admin login in /auth/me")
    print("[ok] auth flow")

    suffix = _timestamp()
    created: dict[str, Any] = {}

    group = admin.request(
        "POST",
        "/groups",
        json_body={"name": f"smoke-group-{suffix}", "description": "smoke test group"},
        expected=201,
    )
    created["group_id"] = group["group_id"]
    print("[ok] groups.create")

    camera = admin.request(
        "POST",
        "/admin/cameras",
        json_body={
            "name": f"smoke-camera-{suffix}",
            "ip_address": args.camera_ip,
            "stream_url": args.camera_stream_url,
            "status_id": 1,
            "location": "Smoke stand",
            "detection_enabled": True,
            "recording_mode": "continuous",
        },
        expected=201,
    )
    created["camera_id"] = camera["camera_id"]
    admin.request("POST", f"/groups/{created['group_id']}/cameras/{created['camera_id']}")
    cameras = admin.request("GET", "/cameras")
    _assert(any(item["camera_id"] == created["camera_id"] for item in cameras), "camera not visible in /cameras")
    print("[ok] cameras/group flow")

    person = admin.request(
        "POST",
        "/persons",
        json_body={"last_name": "Smoke", "first_name": "Tester", "middle_name": suffix[-4:]},
        expected=201,
    )
    created["person_id"] = person["person_id"]
    admin.request(
        "PATCH",
        f"/persons/{created['person_id']}",
        json_body={"middle_name": "Updated"},
    )
    persons = admin.request("GET", "/persons")
    _assert(any(item["person_id"] == created["person_id"] for item in persons), "person not listed")
    print("[ok] persons CRUD")

    user = admin.request(
        "POST",
        "/admin/users",
        json_body={"login": f"smoke_user_{suffix}", "password": "SmokePass123!", "role_id": 3},
        expected=201,
    )
    created["user_id"] = user["user_id"]
    admin.request("POST", f"/admin/users/{created['user_id']}/role", query={"role_id": 2})
    users = admin.request("GET", "/admin/users")
    _assert(any(item["user_id"] == created["user_id"] for item in users), "user not listed")
    print("[ok] admin users CRUD")

    api_key_plain = admin.request(
        "POST",
        "/api-keys",
        json_body={"description": "Smoke test key", "scopes": ["processor:read"]},
        expected=201,
    )
    created["api_key_id"] = api_key_plain["api_key_id"]
    admin.request(
        "PATCH",
        f"/api-keys/{created['api_key_id']}",
        json_body={"description": "Smoke test key updated", "scopes": ["processor:read"], "is_active": True},
    )
    api_keys = admin.request("GET", "/api-keys")
    _assert(any(item["api_key_id"] == created["api_key_id"] for item in api_keys), "api key not listed")
    print("[ok] api-keys CRUD")

    code = admin.request("POST", "/processors/generate-code")
    processor = anon.request(
        "POST",
        "/processors/connect",
        json_body={"code": code["code"], "name": f"smoke-processor-{suffix}", "hostname": "smoke-host", "os_info": "SmokeOS", "version": "1.0.0", "capabilities": {"media_port": 8777, "media_token": "smoke-token"}},
    )
    created["processor_id"] = processor["processor_id"]
    processor_client = ApiClient(args.base_url, api_key=processor["api_key"])
    processor_client.request(
        "POST",
        f"/processors/{created['processor_id']}/heartbeat",
        json_body={
            "status": "online",
            "hostname": "smoke-host",
            "os_info": "SmokeOS",
            "version": "1.0.0",
            "media_port": 8777,
            "media_token": "smoke-token",
            "metrics": {"cpu_percent": 10.0, "ram_total_gb": 16.0},
        },
    )
    admin.request(
        "POST",
        f"/processors/{created['processor_id']}/assign",
        json_body={"camera_ids": [created["camera_id"]]},
    )
    assignments = processor_client.request("GET", f"/processors/{created['processor_id']}/assignments")
    _assert(any(item["camera_id"] == created["camera_id"] for item in assignments), "camera not assigned to processor")
    processor_list = admin.request("GET", "/processors")
    _assert(any(item["processor_id"] == created["processor_id"] for item in processor_list), "processor not listed")
    print("[ok] processor registration/assignment")

    unknown_event = processor_client.request(
        "POST",
        f"/processors/{created['processor_id']}/events",
        json_body={
            "camera_id": created["camera_id"],
            "event_type": "face_unknown",
            "confidence": 0.41,
            "snapshot_b64": TINY_IMAGE_B64,
        },
    )
    pending = admin.request("GET", "/detections/pending")
    _assert(any(item["event_id"] == unknown_event["event_id"] for item in pending), "pending review event not found")
    rejected = admin.request("POST", "/detections/review/reject-all")
    _assert(rejected["updated"] >= 1, "reject-all did not update any reviews")
    print("[ok] detections review")

    recognized_event = processor_client.request(
        "POST",
        f"/processors/{created['processor_id']}/events",
        json_body={
            "camera_id": created["camera_id"],
            "event_type": "face_recognized",
            "person_id": created["person_id"],
            "confidence": 0.91,
            "snapshot_b64": TINY_IMAGE_B64,
        },
    )
    _assert(recognized_event["event_id"] > 0, "recognized event id is invalid")
    report = admin.request("GET", "/reports/appearances", query={"person_id": created["person_id"]})
    _assert(report["total"] >= 1, "appearance report is empty")
    for fmt in ("pdf", "xlsx", "docx"):
        payload, _headers = admin.request(
            "GET",
            "/reports/appearances/export",
            query={"person_id": created["person_id"], "format": fmt},
            expected=200,
            read_json=False,
        )
        _assert(len(payload) > 0, f"empty report export for {fmt}")
    print("[ok] reports")

    recording = processor_client.request(
        "POST",
        f"/processors/{created['processor_id']}/recordings",
        json_body={
            "camera_id": created["camera_id"],
            "file_kind": "video",
            "file_path": f"processor://{created['processor_id']}/recordings/smoke-{suffix}.mp4",
            "duration_seconds": 12.5,
            "file_size_bytes": 123456,
        },
    )
    _assert(recording["recording_file_id"] > 0, "recording file id is invalid")
    recordings = admin.request("GET", "/recordings", query={"camera_id": created["camera_id"]})
    _assert(any(item["recording_file_id"] == recording["recording_file_id"] for item in recordings), "recording not listed")
    storage = processor_client.request("GET", f"/processors/{created['processor_id']}/storage-config")
    _assert(storage["root_path"], "storage config root_path is empty")
    print("[ok] recordings/storage")

    if not args.keep_fixtures:
        admin.request("DELETE", f"/processors/{created['processor_id']}", expected=(200, 204), read_json=False)
        admin.request("DELETE", f"/admin/users/{created['user_id']}", expected=(200, 204), read_json=False)
        admin.request("DELETE", f"/api-keys/{created['api_key_id']}", expected=(200, 204), read_json=False)
        admin.request("DELETE", f"/persons/{created['person_id']}", expected=(200, 204), read_json=False)
        admin.request("DELETE", f"/admin/cameras/{created['camera_id']}", expected=(200, 204), read_json=False)
        persons_after_delete = admin.request("GET", "/persons")
        _assert(
            all(item["person_id"] != created["person_id"] for item in persons_after_delete),
            "soft-deleted person is still visible in active /persons list",
        )
        cameras_after_delete = admin.request("GET", "/cameras")
        _assert(
            all(item["camera_id"] != created["camera_id"] for item in cameras_after_delete),
            "soft-deleted camera is still visible in active /cameras list",
        )
        historical_report = admin.request("GET", "/reports/appearances", query={"person_id": created["person_id"]})
        _assert(historical_report["total"] >= 1, "historical report lost data after soft delete")
        admin.request("DELETE", f"/groups/{created['group_id']}", expected=(200, 204), read_json=False)
        print("[ok] cleanup")

    print("\nSmoke API test completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeError as exc:
        print(f"\nSmoke API test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
