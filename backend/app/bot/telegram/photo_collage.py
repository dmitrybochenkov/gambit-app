import asyncio
import math
from io import BytesIO

from aiogram import Bot
from aiogram.types import BufferedInputFile
from PIL import Image, ImageOps

_CELL_SIZE = 800


async def build_photo_collage(bot: Bot, file_ids: list[str]) -> BufferedInputFile:
    if len(file_ids) < 2:
        raise ValueError("A collage requires at least two photos")
    payloads: list[bytes] = []
    for file_id in file_ids:
        destination = BytesIO()
        await bot.download(file_id, destination=destination)
        payloads.append(destination.getvalue())
    collage = await asyncio.to_thread(_compose_collage, payloads)
    return BufferedInputFile(collage, filename="hall-of-fame-collage.jpg")


def _compose_collage(payloads: list[bytes]) -> bytes:
    columns = math.ceil(math.sqrt(len(payloads)))
    rows = math.ceil(len(payloads) / columns)
    canvas = Image.new("RGB", (columns * _CELL_SIZE, rows * _CELL_SIZE), "white")
    for index, payload in enumerate(payloads):
        with Image.open(BytesIO(payload)) as source:
            tile = ImageOps.fit(source.convert("RGB"), (_CELL_SIZE, _CELL_SIZE))
            canvas.paste(tile, ((index % columns) * _CELL_SIZE, (index // columns) * _CELL_SIZE))
    output = BytesIO()
    canvas.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()
