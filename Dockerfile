FROM debian:bookworm-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    fonts-freefont-ttf \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-core \
    fonts-roboto \
    libharfbuzz0b \
    libnss3 \
    libdrm2 \
    socat \
    dumb-init \
    wget \
    unzip \
    libasound2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libgbm1 \
    libglib2.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Add custom fonts
COPY fonts/ /usr/share/fonts/truetype/custom/
RUN fc-cache -f -v

# Install packages:
# python3, pip, chromium, dumb-init, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    gcc \
    python3-dev \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    mesa-vulkan-drivers \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies:
RUN python3 -m venv /venv
RUN /venv/bin/pip install --upgrade pip
RUN /venv/bin/pip install --no-cache-dir "websockets==11.0.3" "aiohttp==3.9.3"

# Configure environment
RUN useradd -m -u 1000 chromeuser \
    && mkdir -p /home/chromeuser/chrome-data \
    && chown -R chromeuser:chromeuser /home/chromeuser

USER chromeuser
WORKDIR /home/chromeuser
COPY controller.py .

ENV PATH="/venv/bin:$PATH"
ENTRYPOINT ["dumb-init", "/venv/bin/python3", "controller.py"]

