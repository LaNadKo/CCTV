from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, status

from app.routers import face


class FaceHelperTests(unittest.TestCase):
    def test_face_enrollment_requires_admin(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            face._ensure_face_enrollment_admin(SimpleNamespace(role_id=2))

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_face_enrollment_accepts_admin(self) -> None:
        face._ensure_face_enrollment_admin(SimpleNamespace(role_id=1))

    def test_decoded_face_image_pixel_count_is_limited(self) -> None:
        image = SimpleNamespace(ndim=3, shape=(face._MAX_FACE_IMAGE_PIXELS + 1, 1, 3))

        with patch("app.routers.face.cv2.imdecode", return_value=image):
            with self.assertRaises(HTTPException) as ctx:
                face._decode_face_image(b"compressed-image")

        self.assertEqual(ctx.exception.status_code, status.HTTP_413_CONTENT_TOO_LARGE)


if __name__ == "__main__":
    unittest.main()
