FROM python:3.14

ENV DEBIAN_FRONTEND=noninteractive;
RUN apt -qyy update;
RUN apt -qyy upgrade;
RUN apt -qyy install curl;
RUN apt -qyy install python3-full;
RUN apt -qyy install build-essential;
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > /tmp/rustup.sh && \
        chmod a+x /tmp/rustup.sh && \
        /tmp/rustup.sh -y;
RUN apt -qyy install libgirepository1.0-dev libgirepository-2.0-dev gcc cmake libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0 python3-gi python3-gi-cairo;

RUN python3 -m venv /venv
RUN /venv/bin/pip install --upgrade pip
RUN /venv/bin/pip install --upgrade pip-tools cryptography
