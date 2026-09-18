FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
RUN apt-get update && apt-get install -y --no-install-recommends curl git libgl1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir basicsr facexlib fastapi gfpgan opencv-python-headless python-multipart realesrgan uvicorn
WORKDIR /service
COPY docker/realesrgan/server.py ./server.py
EXPOSE 8090
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8090"]
