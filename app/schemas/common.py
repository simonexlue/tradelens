from typing import Literal

AllowedContentType = Literal["image/png", "image/jpeg", "image/webp"]
AllowedExt = Literal["png", "jpg", "jpeg", "webp"]

MIME_TO_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}