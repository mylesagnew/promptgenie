FROM python:3.12-slim

# Non-root user
RUN groupadd --gid 1001 promptgenie \
 && useradd --uid 1001 --gid promptgenie --no-create-home --shell /sbin/nologin promptgenie

WORKDIR /app

# Install dependencies before copying source so this layer is cached
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir ".[benchmark,tokenizer]"

# Copy source after deps to maximise cache reuse
COPY promptgenie/ ./promptgenie/

# Install the package itself (editable not needed in image — use regular install)
RUN pip install --no-cache-dir --no-deps .

USER promptgenie

ENTRYPOINT ["promptgenie"]
CMD ["--help"]
