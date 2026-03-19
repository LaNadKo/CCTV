from typing import Union

from app import models


def resolve_source(cam: models.Camera) -> Union[int, str]:
    """Choose an OpenCV-friendly source from stored fields."""
    if cam.stream_url:
        if cam.stream_url.startswith("local"):
            parts = cam.stream_url.split(":")
            if len(parts) == 1 or parts[1] == "":
                return 0
            try:
                return int(parts[1])
            except ValueError:
                return cam.stream_url
        return cam.stream_url
    if cam.ip_address:
        return cam.ip_address
    return 0  # fallback to default laptop webcam
