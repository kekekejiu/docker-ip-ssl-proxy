FROM python:3.12-alpine

RUN apk add --no-cache openssl

WORKDIR /app
COPY zerossl.py http_verify.py webroot_verify.py entrypoint.py ./

ENV CERT_DIR=/certs \
    STATE_DIR=/state \
    PYTHONUNBUFFERED=1

VOLUME ["/certs", "/state"]

ENTRYPOINT ["python3", "/app/entrypoint.py"]
