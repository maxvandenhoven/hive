# Start from a slim python base image to keep the container size as small as possible.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /bin/

# Set the shell to bash instead of sh, using pipefail to identify silent pipe errors.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set the working directory for consistent paths in notebooks/tests.
WORKDIR /workspaces/hive

# Specify the uv cache directory in the working directory to prevent hardlink issues 
# during bind mounting, caused by the default cache location in the container being on a 
# different file system than the working directory on the host machine. Also set default
# locales to prevent issues with pre-commit.
ENV UV_CACHE_DIR=/workspaces/hive/.cache/uv LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Install system packages needed for Git highlighting in the Dev Container. Also install
# the en_US.UTF-8 locales, as VSCode uses these when running pre-commit hooks in Git.
RUN apt-get update \
  && apt-get install -y --no-install-recommends bash-completion curl git locales make \
  && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
  && locale-gen \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Install Dev Container-wide Python packages to be managed outside of uv projects.
RUN pip install pre-commit==4.5.1
