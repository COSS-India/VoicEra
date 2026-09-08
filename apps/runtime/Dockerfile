FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY apps/runtime/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/__init__.py apps/__init__.py
COPY apps/runtime apps/runtime
COPY apps/providers apps/providers
COPY apps/telephony apps/telephony

ENV PYTHONPATH=/app
# Bundled at build time (apps/runtime/nltk_data/) so pipeline setup never blocks
# on a runtime download of NLTK's punkt_tab sentence tokenizer — see
# pipecat/utils/string.py's module docstring.
ENV NLTK_DATA=/app/apps/runtime/nltk_data

EXPOSE 7860

CMD ["uvicorn", "apps.runtime.app:app", "--host", "0.0.0.0", "--port", "7860"]
