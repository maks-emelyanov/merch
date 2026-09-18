from __future__ import annotations

from typing import Annotated

import cv2
import numpy as np
import torch
from basicsr.archs.rrdbnet_arch import RRDBNet
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
from realesrgan import RealESRGANer

app = FastAPI()
model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
upsampler = RealESRGANer(
    scale=4,
    model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/RealESRGAN_x4plus.pth",
    model=model,
    tile=512,
    tile_pad=10,
    pre_pad=0,
    half=torch.cuda.is_available(),
)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"healthy": torch.cuda.is_available()}


@app.post("/upscale")
async def upscale(image: Annotated[UploadFile, File()]) -> Response:
    raw = await image.read()
    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    alpha = None
    if decoded.ndim == 3 and decoded.shape[2] == 4:
        alpha = decoded[:, :, 3]
        decoded = decoded[:, :, :3]
    output, _ = upsampler.enhance(decoded, outscale=4)
    if alpha is not None:
        resized_alpha = cv2.resize(
            alpha, (output.shape[1], output.shape[0]), interpolation=cv2.INTER_LANCZOS4
        )
        output = np.dstack((output, resized_alpha))
    ok, encoded = cv2.imencode(".png", output)
    if not ok:
        raise RuntimeError("Real-ESRGAN encoding failed")
    return Response(encoded.tobytes(), media_type="image/png")
