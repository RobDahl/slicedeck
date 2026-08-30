# Runs the API and serves the demo page.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so edits to the source do not invalidate the layer.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[server]"

COPY web ./web

ENV SLICEDECK_SOURCE=synthetic \
    SLICEDECK_HOST=0.0.0.0 \
    SLICEDECK_PORT=8080
EXPOSE 8080

# Non-root: nothing here needs privileges unless USB HID is passed through.
RUN useradd --create-home slicedeck && chown -R slicedeck /app
USER slicedeck

CMD ["slicedeck", "--serve"]
