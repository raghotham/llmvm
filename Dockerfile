FROM python:3.12-slim
WORKDIR /llmvm

# we grab the keys from the terminal environment
# use the --build-arg flag to pass in the keys
ARG OPENAI_API_KEY
ARG ANTHROPIC_API_KEY
ARG GEMINI_API_KEY
ARG LLAMA_API_KEY
ARG SEC_API_KEY
ARG SERPAPI_API_KEY
ARG LLMVM_SERVER_PORT=8011
ARG NGINX_PORT=8080

ENV container docker
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8
ENV DEBIAN_FRONTEND=noninteractive
ENV LLMVM_SERVER_PORT=${LLMVM_SERVER_PORT}
ENV NGINX_PORT=${NGINX_PORT}

RUN useradd -m -d /llmvm -s /bin/bash llmvm
RUN mkdir -p /var/run/sshd
RUN mkdir -p /run/sshd

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    openssh-server \
    rsync \
    poppler-utils \
    build-essential \
    nginx \
    gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

RUN echo 'llmvm:llmvm' | chpasswd
RUN service ssh start

# ssh
EXPOSE 2222
# llmvm.server (uses LLMVM_SERVER_PORT env var, default 8011)
EXPOSE 8011
# website (uses NGINX_PORT env var, default 8080)
EXPOSE 8080

# copy over the source and data
COPY ./ /llmvm/

RUN mkdir -p /llmvm/.config/llmvm \
    /llmvm/.tmp \
    /llmvm/.cache \
    /llmvm/.local/share/llmvm/cache \
    /llmvm/.local/share/llmvm/download \
    /llmvm/.local/share/llmvm/logs \
    /llmvm/.local/share/llmvm/memory \
    /llmvm/.ssh

RUN chown -R llmvm:llmvm /llmvm

# Create a separate SSH config for standard shell access
RUN mkdir -p /etc/ssh/sshd_config.d
RUN cp /etc/ssh/sshd_config /etc/ssh/sshd_config_standard
RUN sed -i 's/^#Port 22/Port 2222/' /etc/ssh/sshd_config_standard
RUN sed -i '/Match User llmvm/,/ForceCommand/d' /etc/ssh/sshd_config_standard
RUN echo 'PidFile /var/run/sshd_standard.pid' >> /etc/ssh/sshd_config_standard

# Switch to llmvm user
USER llmvm

ENV HOME /llmvm
ENV TMPDIR /llmvm/.tmp

WORKDIR /llmvm

# Install uv
RUN pip install uv

# Install requirements using uv
RUN uv sync --frozen
RUN uv run pip install playwright

# Switch to root to install playwright system dependencies
USER root
RUN uv run playwright install-deps
USER llmvm

COPY ./llmvm/config.yaml /llmvm/.config/llmvm/config.yaml

RUN echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> /llmvm/.ssh/environment
RUN echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" >> /llmvm/.ssh/environment
RUN echo "GEMINI_API_KEY=$GEMINI_API_KEY" >> /llmvm/.ssh/environment
RUN echo "LLAMA_API_KEY=$LLAMA_API_KEY" >> /llmvm/.ssh/environment
RUN echo "SEC_API_KEY=$SEC_API_KEY" >> /llmvm/.ssh/environment
RUN echo "SERPAPI_API_KEY=$SERPAPI_API_KEY" >> /llmvm/.ssh/environment

RUN uv run playwright install

# Build the SDK first
WORKDIR /llmvm/web/js-llmvm-sdk
RUN npm install
RUN npm run build

# Build the website
WORKDIR /llmvm/web/llmvm-chat-studio
# Add the SDK as a local dependency and install
RUN npm install ../js-llmvm-sdk
RUN npm install
RUN npm run build
# Copy the config template to dist
RUN cp public/config.js.template dist/config.js.template

# Copy the wrapper script from the scripts directory and make it executable
WORKDIR /llmvm
COPY --chmod=755 ./scripts/llmvm-client-wrapper.sh /llmvm/llmvm-client-wrapper.sh

# spin back to root, to start sshd
USER root

# Configure nginx
COPY ./docker/nginx.conf.template /etc/nginx/sites-available/llmvm-web.template
RUN ln -s /etc/nginx/sites-available/llmvm-web /etc/nginx/sites-enabled/
RUN rm -f /etc/nginx/sites-enabled/default

RUN sed -i 's/^#Port 22/Port 2222/' /etc/ssh/sshd_config
RUN echo 'PermitUserEnvironment yes' >> /etc/ssh/sshd_config
RUN echo 'PermitUserEnvironment yes' >> /etc/ssh/sshd_config_standard

# Configure SSH to use the wrapper script as the shell for the llmvm user
RUN echo 'Match User llmvm' >> /etc/ssh/sshd_config_standard && \
    echo '    ForceCommand /llmvm/llmvm-client-wrapper.sh' >> /etc/ssh/sshd_config_standard

WORKDIR /llmvm

ENTRYPOINT service ssh restart; \
    envsubst '${NGINX_PORT}' < /etc/nginx/sites-available/llmvm-web.template > /etc/nginx/sites-available/llmvm-web; \
    envsubst '${LLMVM_SERVER_PORT}' < /llmvm/web/llmvm-chat-studio/dist/config.js.template > /llmvm/web/llmvm-chat-studio/dist/config.js; \
    service nginx start; \
    /usr/sbin/sshd -f /etc/ssh/sshd_config; \
    /usr/sbin/sshd -f /etc/ssh/sshd_config_standard; \
    runuser -u llmvm -- bash -c 'cd /llmvm; LLMVM_FULL_PROCESSING="true" LLMVM_EXECUTOR_TRACE="/llmvm/.local/share/llmvm/executor.trace" LLMVM_PROFILING="true" uv run python -m llmvm.server.server'
