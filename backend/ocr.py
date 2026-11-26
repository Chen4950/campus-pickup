import re
import unicodedata
from io import BytesIO
from threading import Lock

from PIL import Image, ImageOps, UnidentifiedImageError

SEPARATOR = r"\s*[-‐–—·]\s*"
SHELF_CODE = re.compile(r"(?<![A-Z0-9])([A-Z][0-9]{1,3})" + SEPARATOR + r"([0-9]{1,2})" + SEPARATOR + r"([0-9]{4})(?![0-9])")
PICKUP_CODE = re.compile(r"取件码\s*[:：]?\s*([A-Z]?[0-9]{3,8})(?![A-Z0-9])")
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 12_000_000


def candidates_from_text(lines, shelves):
    candidates = {}
    for raw, confidence in lines:
        text = unicodedata.normalize("NFKC", raw).upper()
        for shelf, level, suffix in SHELF_CODE.findall(text):
            code = f"{shelf}-{level}-{suffix}"
            candidates[code] = {
                "code": code,
                "shelf": shelf if shelf in shelves else "",
                "level": level,
                "suffix": suffix,
                "needs_shelf": shelf not in shelves,
                "confidence": confidence,
            }
        for code in PICKUP_CODE.findall(text):
            candidates[code] = {
                "code": code,
                "shelf": "",
                "level": "",
                "suffix": "",
                "needs_shelf": True,
                "confidence": confidence,
            }
    return list(candidates.values())


class ScreenshotReader:
    def __init__(self):
        self.engine = None
        self.lock = Lock()

    def read(self, payload):
        try:
            with Image.open(BytesIO(payload), formats=["PNG", "JPEG", "WEBP"]) as source:
                if source.width * source.height > MAX_PIXELS:
                    raise ValueError("图片尺寸过大，请裁剪取件通知后再试。")
                image = ImageOps.exif_transpose(source).convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("请上传可打开的 JPG、PNG 或 WebP 图片。") from error
        image.thumbnail((2400, 2400))
        try:
            import numpy as np
            with self.lock:
                if self.engine is None:
                    self.engine = self._load_engine()
                return self._recognize(np.asarray(image))
        except Exception as error:
            raise RuntimeError("截图识别暂不可用，请手动录入货号。") from error

    @staticmethod
    def _load_engine():
        from rapidocr import RapidOCR
        return RapidOCR()

    def _recognize(self, rgb):
        result = self.engine(rgb[:, :, ::-1].copy())
        return [(text, round(float(score), 3)) for text, score in zip(result.txts or (), result.scores or ())]
