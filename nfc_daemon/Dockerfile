FROM python:3.12-slim

WORKDIR /app

# nfcpy needs libusb at runtime for real PN532 support. We only install it when
# building with --build-arg WITH_HARDWARE=1 to keep simulator builds tiny and
# to avoid apt-get layers in environments where apparmor blocks them.
ARG WITH_HARDWARE=0
RUN if [ "$WITH_HARDWARE" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends libusb-1.0-0 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY nfc_daemon/requirements.txt /app/requirements.txt
# nfcpy is only required for real hardware. Skip it in simulator-only builds
# where libusb may not be installable.
RUN if [ "$WITH_HARDWARE" = "1" ]; then \
        pip install --no-cache-dir -r /app/requirements.txt; \
    else \
        grep -v '^nfcpy' /app/requirements.txt | pip install --no-cache-dir -r /dev/stdin; \
    fi
COPY nfc_daemon/ /app/

CMD ["python3", "-u", "daemon.py"]
