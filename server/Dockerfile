FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install the app + its runtime dependencies (asyncpg ships manylinux wheels, so no build
# toolchain is needed).
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .

# Bake the U2-Net weights into the image so background removal works offline and the first
# scan doesn't stall on a ~170 MB download at request time.
RUN python -c "from rembg import new_session; new_session('u2net')"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Strip any CR so a Windows (CRLF) checkout doesn't break the shebang (exit 127).
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
