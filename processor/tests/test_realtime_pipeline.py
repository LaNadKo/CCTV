from __future__ import annotations

import queue
import socket
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

from cctv_ai.model_artifacts import file_matches_sha256, safe_extract_zip
from processor.detection import CameraWorker
from processor.embedding_service import EmbeddingService
from processor.inference_scheduler import PriorityInferenceGate
from processor.latest_queue import put_latest
from processor.media_server import _parse_float, _parse_int, _resize_for_max_width
from processor.network_policy import validate_camera_endpoint_url, validate_camera_host, validate_camera_stream_source
from processor.performance import PerformanceMetrics


def _body(
    box: tuple[int, int, int, int],
    *,
    external_track_id: int | None = None,
) -> dict[str, object]:
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    points = [[0.0, 0.0] for _ in range(17)]
    confidence = [0.0 for _ in range(17)]
    for index, x_ratio, y_ratio in (
        (0, 0.50, 0.12),
        (1, 0.44, 0.10),
        (2, 0.56, 0.10),
        (5, 0.36, 0.32),
        (6, 0.64, 0.32),
        (7, 0.30, 0.48),
        (8, 0.70, 0.48),
        (9, 0.26, 0.64),
        (10, 0.74, 0.64),
        (11, 0.40, 0.72),
        (12, 0.60, 0.72),
    ):
        points[index] = [x1 + width * x_ratio, y1 + height * y_ratio]
        confidence[index] = 0.95
    return {
        "box": box,
        "tracking_box": box,
        "track_id": external_track_id,
        "confidence": 0.95,
        "keypoints": points,
        "keypoint_conf": confidence,
        "frame_size": (640, 480),
        "head_points": [points[0], points[1], points[2]],
        "head_box": (
            int(x1 + width * 0.30),
            y1,
            int(x1 + width * 0.70),
            int(y1 + height * 0.30),
        ),
        "head_only": False,
    }


def _worker() -> CameraWorker:
    worker = object.__new__(CameraWorker)
    worker._body_tracks = {}
    worker._next_body_track_id = 1
    worker._recognized_track_hold_seconds = 4.5
    worker._track_visible_ttl = 0.3
    worker._track_reacquire_ttl = 1.5
    worker._spoof_face_boxes = []
    worker._blocked_face_boxes = []
    worker._spoof_face_ttl = 12.0
    worker._last_faces_info = []
    worker._last_faces_ts = 0.0
    worker._last_faces_flow_ts = 0.0
    worker._last_body_info = []
    worker._last_body_ts = 0.0
    worker._last_body_flow_ts = 0.0
    worker._face_overlay_ttl = 1.5
    worker._body_overlay_ttl = 1.5
    worker._face_flow_ttl = 2.5
    worker._body_flow_ttl = 2.5
    return worker


class LatestQueueTests(unittest.TestCase):
    def test_latest_item_replaces_stale_item(self) -> None:
        target: queue.Queue[int] = queue.Queue(maxsize=1)
        put_latest(target, 1)
        put_latest(target, 2)
        self.assertEqual(target.get_nowait(), 2)


class InferenceSchedulerTests(unittest.TestCase):
    def test_live_waiter_runs_before_background_waiter(self) -> None:
        gate = PriorityInferenceGate()
        order: list[str] = []
        active = threading.Event()

        def first_background() -> None:
            with gate.background():
                active.set()
                time.sleep(0.08)
                order.append("background-active")

        def live() -> None:
            active.wait()
            with gate.live():
                order.append("live")

        def second_background() -> None:
            active.wait()
            time.sleep(0.01)
            with gate.background():
                order.append("background-waiting")

        threads = [
            threading.Thread(target=first_background),
            threading.Thread(target=live),
            threading.Thread(target=second_background),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertEqual(
            order,
            ["background-active", "live", "background-waiting"],
        )


class BodyTrackingTests(unittest.TestCase):
    def test_smooth_motion_keeps_track_id(self) -> None:
        worker = _worker()
        first = worker._update_body_tracks([_body((100, 80, 220, 360))], 1.0)
        second = worker._update_body_tracks([_body((112, 84, 232, 364))], 1.1)

        self.assertEqual(first[0]["track_id"], second[0]["track_id"])
        self.assertEqual(second[0]["hits"], 2)

    def test_impossible_jump_creates_new_track(self) -> None:
        worker = _worker()
        first = worker._update_body_tracks([_body((100, 80, 220, 360))], 1.0)
        second = worker._update_body_tracks([_body((900, 80, 1020, 360))], 1.1)
        visible = [state for state in second if state.get("visible")]

        self.assertNotEqual(first[0]["track_id"], visible[0]["track_id"])
        self.assertFalse(worker._body_tracks[int(first[0]["track_id"])]["visible"])

    def test_track_is_hidden_before_reacquire_timeout(self) -> None:
        worker = _worker()
        first = worker._update_body_tracks([_body((100, 80, 220, 360))], 1.0)
        track_id = int(first[0]["track_id"])
        worker._update_body_tracks([], 1.35)

        self.assertIn(track_id, worker._body_tracks)
        self.assertFalse(worker._body_tracks[track_id]["visible"])

    def test_flow_timestamp_is_used_for_track_prediction(self) -> None:
        worker = _worker()
        state = _body((100, 80, 220, 360))
        state["last_seen"] = 1.0
        state["last_flow_seen"] = 1.4
        state["velocity"] = (100.0, 0.0, 0.0, 0.0)

        predicted = worker._predict_track_box(state, 1.5)

        self.assertEqual(predicted, (110, 80, 230, 360))

    def test_head_shoulders_and_arms_without_torso_are_enough(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        confidence[11] = 0.0
        confidence[12] = 0.0
        body["keypoint_conf"] = confidence

        self.assertTrue(worker._track_has_minimum_upper_pose(body))

    def test_head_shoulders_and_one_arm_are_enough(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        confidence[8] = 0.0
        confidence[10] = 0.0
        body["keypoint_conf"] = confidence

        self.assertTrue(worker._track_has_minimum_upper_pose(body))

    def test_upper_pose_accepts_relaxed_nearby_wrist(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        keypoints = list(body["keypoints"])
        confidence = list(body["keypoint_conf"])
        for index in (7, 8, 9, 10):
            confidence[index] = 0.0
        keypoints[9] = [80.0, 275.0]
        confidence[9] = 0.19
        body["keypoints"] = keypoints
        body["keypoint_conf"] = confidence

        self.assertTrue(worker._track_has_minimum_upper_pose(body))

    def test_edge_arm_point_does_not_activate_body_track(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        keypoints = list(body["keypoints"])
        confidence = list(body["keypoint_conf"])
        for index in (7, 8, 9, 10):
            confidence[index] = 0.0
        keypoints[9] = [2.0, 275.0]
        confidence[9] = 0.99
        body["keypoints"] = keypoints
        body["keypoint_conf"] = confidence

        self.assertFalse(worker._track_has_minimum_upper_pose(body))

    def test_head_shoulders_without_arms_are_not_enough(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        for index in (7, 8, 9, 10):
            confidence[index] = 0.0
        body["keypoint_conf"] = confidence

        self.assertFalse(worker._track_has_minimum_upper_pose(body))

    def test_missing_shoulders_are_not_drawable(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        confidence[5] = 0.0
        confidence[6] = 0.0
        body["keypoint_conf"] = confidence

        self.assertFalse(worker._track_has_minimum_upper_pose(body))

    def test_absurd_shoulder_geometry_is_not_drawable(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        keypoints = list(body["keypoints"])
        keypoints[5] = [95.0, 120.0]
        keypoints[6] = [620.0, 420.0]
        body["keypoints"] = keypoints

        self.assertFalse(worker._track_has_minimum_upper_pose(body))

    def test_spoof_overlap_hides_body_overlay(self) -> None:
        worker = _worker()
        now = 10.0
        body = _body((100, 80, 220, 360))
        body["track_id"] = 7
        body["hits"] = 3
        worker._remember_spoof_face((125, 85, 195, 180), now)

        self.assertEqual(worker._build_body_overlay_items([body], now), [])

    def test_flying_limb_keypoints_are_not_drawable(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        keypoints = list(body["keypoints"])
        confidence = list(body["keypoint_conf"])
        keypoints[9] = [920.0, 60.0]
        confidence[9] = 0.99
        body["keypoints"] = keypoints
        body["keypoint_conf"] = confidence

        drawable = worker._body_drawable_keypoints(body, (480, 640, 3))

        self.assertIn(5, drawable)
        self.assertIn(6, drawable)
        self.assertIn(7, drawable)
        self.assertNotIn(9, drawable)

    def test_torso_only_keypoints_do_not_draw_square_skeleton(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        for index in (7, 8, 9, 10, 13, 14, 15, 16):
            confidence[index] = 0.0
        body["keypoint_conf"] = confidence

        drawable = worker._body_drawable_keypoints(body, (480, 640, 3))

        self.assertEqual(drawable, {})

    def test_upper_body_without_hips_is_drawable(self) -> None:
        worker = _worker()
        body = _body((100, 80, 220, 360))
        confidence = list(body["keypoint_conf"])
        confidence[11] = 0.0
        confidence[12] = 0.0
        body["keypoint_conf"] = confidence

        drawable = worker._body_drawable_keypoints(body, (480, 640, 3))

        self.assertIn(5, drawable)
        self.assertIn(6, drawable)
        self.assertIn(7, drawable)
        self.assertIn(9, drawable)
        self.assertNotIn(11, drawable)
        self.assertNotIn(12, drawable)

    def test_flow_does_not_extend_face_overlay_ttl(self) -> None:
        worker = _worker()
        worker._analysis_lock = threading.Lock()
        worker._last_faces_info = [((10, 10, 30, 30), "РќРµРёР·РІРµСЃС‚РЅРѕ", False)]
        face_ts = time.time()
        worker._last_faces_ts = face_ts
        worker._last_faces_flow_ts = face_ts
        worker._face_flow_ttl = 10.0
        worker._face_flow_reference = "previous"
        worker._last_body_info = []
        worker._last_body_ts = 0.0
        worker._last_body_flow_ts = 0.0
        worker._body_flow_ttl = 0.0

        worker._make_flow_reference = lambda _frame: "current"
        worker._track_overlay_points = (
            lambda _previous, _current, _points, _shape: ({0: (15.0, 10.0)}, (5.0, 0.0))
        )
        worker._shift_overlay_box = (
            lambda box, dx, dy, _shape: tuple(int(value + (dx if index % 2 == 0 else dy)) for index, value in enumerate(box))
        )

        worker._advance_overlay_geometry(np.zeros((100, 100, 3), dtype=np.uint8))

        self.assertEqual(worker._last_faces_info[0][0], (15, 10, 35, 30))
        self.assertEqual(worker._face_flow_reference, "current")
        self.assertEqual(worker._last_faces_ts, face_ts)
        self.assertGreaterEqual(worker._last_faces_flow_ts, face_ts)

    def test_body_flow_does_not_rewrite_canonical_keypoints(self) -> None:
        worker = _worker()
        worker._analysis_lock = threading.Lock()
        body = _body((100, 80, 220, 360))
        body["track_id"] = 7
        body["hits"] = 3
        worker._body_tracks[7] = dict(body)
        worker._last_body_info = [dict(body)]
        worker._last_body_ts = time.time()
        worker._last_body_flow_ts = worker._last_body_ts
        worker._body_flow_ttl = 10.0
        worker._body_flow_reference = "previous"
        worker._last_faces_info = []
        worker._last_faces_ts = 0.0
        worker._last_faces_flow_ts = 0.0
        worker._face_flow_ttl = 0.0
        original_keypoints = [list(point) for point in body["keypoints"]]

        worker._make_flow_reference = lambda _frame: "current"
        worker._track_overlay_points = (
            lambda _previous, _current, _points, _shape: ({0: (_points[0][0] + 8.0, _points[0][1])}, (8.0, 0.0))
        )
        worker._shift_overlay_box = (
            lambda box, dx, dy, _shape: tuple(int(value + (dx if index % 2 == 0 else dy)) for index, value in enumerate(box))
        )

        worker._advance_overlay_geometry(np.zeros((480, 640, 3), dtype=np.uint8))

        self.assertEqual(worker._body_tracks[7]["keypoints"], original_keypoints)
        self.assertEqual(worker._body_tracks[7]["tracking_box"], (108, 80, 228, 360))


class OverlayStabilityTests(unittest.TestCase):
    def test_face_overlay_remains_active_without_recent_flow_inside_ttl(self) -> None:
        worker = _worker()
        now = 100.0
        worker._last_faces_info = [((10, 10, 30, 30), "pending", False)]
        worker._last_faces_ts = now - 1.0
        worker._last_faces_flow_ts = now - 0.9

        self.assertEqual(worker._overlay_active_flags(now), (True, False))

    def test_flow_does_not_extend_face_overlay_past_detection_ttl(self) -> None:
        worker = _worker()
        now = 100.0
        worker._last_faces_info = [((10, 10, 30, 30), "pending", False)]
        worker._last_faces_ts = now - 1.6
        worker._last_faces_flow_ts = now

        self.assertEqual(worker._overlay_active_flags(now), (False, False))

    def test_body_overlay_remains_active_without_recent_flow_inside_ttl(self) -> None:
        worker = _worker()
        now = 100.0
        worker._last_body_info = [_body((100, 80, 220, 360))]
        worker._last_body_ts = now - 1.0
        worker._last_body_flow_ts = now - 0.9

        self.assertEqual(worker._overlay_active_flags(now), (False, True))


class PerformanceMetricsTests(unittest.TestCase):
    def test_snapshot_reports_average_and_p95(self) -> None:
        metrics = PerformanceMetrics("test")
        metrics.observe("capture", 0.001)
        metrics.observe("capture", 0.003)

        summary = metrics.snapshot()["capture"]
        self.assertEqual(summary.count, 2)
        self.assertAlmostEqual(summary.average_ms, 2.0)
        self.assertAlmostEqual(summary.p95_ms, 3.0)

    def test_bottleneck_text_reports_slowest_metric(self) -> None:
        metrics = PerformanceMetrics("test")
        metrics.observe("capture", 0.001)
        metrics.observe("overlay", 0.020)

        self.assertIn("overlay", metrics.bottleneck_text())


class MediaServerHelperTests(unittest.TestCase):
    def test_query_parsing_clamps_recording_preview_values(self) -> None:
        self.assertEqual(_parse_int("9999", default=960, minimum=320, maximum=1920), 1920)
        self.assertEqual(_parse_int("10", default=960, minimum=320, maximum=1920), 320)
        self.assertEqual(_parse_int("bad", default=72, minimum=40, maximum=95), 72)
        self.assertEqual(_parse_float("12.5", default=8.0), 12.5)
        self.assertEqual(_parse_float("bad", default=8.0), 8.0)

    def test_resize_for_max_width_preserves_aspect_ratio(self) -> None:
        frame = np.zeros((480, 1280, 3), dtype=np.uint8)
        resized = _resize_for_max_width(frame, 640)
        self.assertEqual(resized.shape[:2], (240, 640))

        small = np.zeros((240, 320, 3), dtype=np.uint8)
        self.assertIs(_resize_for_max_width(small, 640), small)


class NetworkPolicyTests(unittest.TestCase):
    def test_lan_camera_sources_are_allowed(self) -> None:
        self.assertEqual(validate_camera_host("192.168.88.242"), "192.168.88.242")
        resolved = [(None, None, None, "", ("192.168.88.242", 0))]
        with patch("processor.network_policy.socket.getaddrinfo", return_value=resolved):
            self.assertEqual(validate_camera_host("C200"), "C200")
        self.assertEqual(
            validate_camera_stream_source("rtsp://192.168.88.242:554/stream1"),
            "rtsp://192.168.88.242:554/stream1",
        )
        self.assertEqual(
            validate_camera_endpoint_url("onvif", "http://192.168.88.242:2020/onvif/device_service"),
            "http://192.168.88.242:2020/onvif/device_service",
        )

    def test_local_and_link_local_sources_are_blocked(self) -> None:
        for host in ("localhost", "127.0.0.1", "::1", "169.254.169.254"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    validate_camera_host(host)
        for url in ("file:///C:/Windows/win.ini", "http:///missing-host", "http://127.0.0.1:8001/health"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    validate_camera_stream_source(url)

    def test_hostname_resolving_to_blocked_address_is_rejected(self) -> None:
        resolved = [(None, None, None, "", ("127.0.0.1", 0))]
        with patch("processor.network_policy.socket.getaddrinfo", return_value=resolved):
            with self.assertRaises(ValueError):
                validate_camera_stream_source("rtsp://camera.local:554/stream1")

    def test_hostname_source_is_pinned_to_resolved_safe_ip(self) -> None:
        resolved = [(None, None, None, "", ("192.168.88.242", 0))]
        with patch("processor.network_policy.socket.getaddrinfo", return_value=resolved):
            self.assertEqual(
                validate_camera_stream_source("rtsp://user:pass@camera.lan:554/stream1"),
                "rtsp://user:pass@192.168.88.242:554/stream1",
            )

    def test_unresolved_hostname_is_rejected(self) -> None:
        with patch("processor.network_policy.socket.getaddrinfo", side_effect=socket.gaierror()):
            with self.assertRaises(ValueError):
                validate_camera_stream_source("rtsp://missing-camera.lan:554/stream1")


class ModelArtifactTests(unittest.TestCase):
    def test_file_checksum_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "model.bin"
            path.write_bytes(b"verified-model")
            self.assertTrue(
                file_matches_sha256(
                    path,
                    "3326723577b96bc7d05ecdb8a32ac917ce7eb053152f145b609635ebdbaf8d46",
                )
            )
            self.assertFalse(file_matches_sha256(path, "0" * 64))

    def test_safe_extract_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            archive_path = root / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", b"blocked")
            destination = root / "models"
            with self.assertRaises(ValueError):
                safe_extract_zip(
                    archive_path,
                    destination,
                    max_members=4,
                    max_uncompressed_bytes=1024,
                )
            self.assertFalse((root / "escape.txt").exists())

    def test_safe_extract_enforces_uncompressed_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            archive_path = root / "large.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("model.bin", b"x" * 64)
            with self.assertRaises(ValueError):
                safe_extract_zip(
                    archive_path,
                    root / "models",
                    max_members=4,
                    max_uncompressed_bytes=32,
                )


class EmbeddingServiceTests(unittest.TestCase):
    def test_queue_is_bounded(self) -> None:
        service = EmbeddingService(queue_size=1)
        self.assertEqual(service._queue.maxsize, 1)


if __name__ == "__main__":
    unittest.main()
