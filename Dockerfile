FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y locales && \
	sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales
    
RUN apt-get update && apt-get install -y \
    python3-tk libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

    
ENV LC_ALL en_US.UTF-8 
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en 
ENV YASPE_IN_CONTAINER True 

COPY requirements.txt requirements.txt
RUN pip3 -V
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt --default-timeout=100 --no-cache-dir

COPY . .

# Set the display environment variable
ENV DISPLAY=:0
