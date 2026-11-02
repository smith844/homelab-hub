FROM python:3.12-alpine

# The scanner has no Python dependencies; nmap is the only runtime requirement.
RUN apk add --no-cache nmap

WORKDIR /app
COPY hlh_scanner /app/hlh_scanner

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HLH_SCANNER_BIND=127.0.0.1 \
    HLH_SCANNER_PORT=8791

EXPOSE 8791
CMD ["python", "-m", "hlh_scanner.server"]
