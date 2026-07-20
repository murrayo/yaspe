FROM python:3.11-slim

WORKDIR /app

# en_US.UTF-8 locale — yaspe parses number formats from many customer locales
RUN apt-get update && \
    apt-get install -y --no-install-recommends locales && \
    sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    rm -rf /var/lib/apt/lists/*

ENV LC_ALL=en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV YASPE_IN_CONTAINER=True
# matplotlib uses the headless Agg backend; give it a writable config dir
# so the image also works when run with --user
ENV MPLCONFIGDIR=/tmp/mpl

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir --default-timeout=100 -r requirements.txt

COPY . .

# survive source downloads that lose the executable bit (e.g. zip on Windows)
RUN chmod +x yaspe.py pretty_performance.py
