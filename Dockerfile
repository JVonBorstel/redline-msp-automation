# B-98 packaged demo image. UNVERIFIED: written on a machine with no Docker, so it has never been built or run.
# Independently built prototype. Not affiliated with any vendor's or real company's systems. Synthetic data only.
#
#   docker compose run --rm demo      # the packaged demo transcript (no network)
#   docker compose run --rm smoke     # the demo smoke test and the audit tests inside the image
#
# Building needs a network once (the base image, uv, and the packages pinned in uv.lock); running does not.
# The approval page is not published to the host: it refuses any address but 127.0.0.1 (SC-3), and inside a
# container that address is not reachable from outside. The PowerShell suites need pwsh, which this image omits;
# the Python smoke tests do not.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN pip install --no-cache-dir uv \
    && useradd --create-home --uid 10001 app

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN chown -R app:app /app /opt/venv
USER app

CMD ["uv", "run", "--frozen", "python", "tools/packaged_demo.py"]
