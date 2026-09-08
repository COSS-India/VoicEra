# A proxy, not a model server: no CUDA, no weights, no torch. It holds one
# WebSocket per gRPC stream and translates. Kept deliberately trivial so it can
# be merged into another image by a caller who needs a single container -- NVCF
# container functions are one container; a Helm function can be two.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY asr.proto server.py ./
# Stubs are generated at build time rather than committed: generated code in a
# repo drifts from the .proto beside it and nothing notices.
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. asr.proto

EXPOSE 8004
CMD ["python", "server.py"]
