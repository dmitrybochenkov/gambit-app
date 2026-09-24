from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.bot.telegram.photo_collage import build_photo_collage


def _jpeg(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (40, 60), color).save(output, format="JPEG")
    return output.getvalue()


async def test_photo_collage_downloads_and_renders_every_photo() -> None:
    payloads = {
        "one": _jpeg("red"),
        "two": _jpeg("green"),
        "three": _jpeg("blue"),
        "four": _jpeg("yellow"),
        "five": _jpeg("magenta"),
    }
    downloaded: list[str] = []

    async def download(file_id: str, *, destination: BytesIO) -> None:
        downloaded.append(file_id)
        destination.write(payloads[file_id])

    collage = await build_photo_collage(
        SimpleNamespace(download=download),
        list(payloads),
    )

    assert downloaded == list(payloads)
    assert collage.filename == "hall-of-fame-collage.jpg"
    with Image.open(BytesIO(collage.data)) as image:
        assert image.size == (2400, 1600)
        expected = [
            (254, 0, 0),
            (0, 128, 1),
            (0, 0, 254),
            (255, 255, 0),
            (255, 0, 254),
        ]
        centers = [(400, 400), (1200, 400), (2000, 400), (400, 1200), (1200, 1200)]
        for center, color in zip(centers, expected, strict=True):
            actual = image.getpixel(center)
            assert all(abs(channel - target) <= 3 for channel, target in zip(actual, color))
