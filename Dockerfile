# Pin base image to a specific digest to prevent supply-chain attacks from
# mutable tags.  To update: docker pull python:3.12-slim && docker inspect
# python:3.12-slim --format='{{index .RepoDigests 0}}'
FROM python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003

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
