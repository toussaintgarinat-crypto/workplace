FROM matrixdotorg/dendrite-monolith:v0.13.7
USER root
RUN apt-get update -qq 2>/dev/null && apt-get install -y -qq gettext-base 2>/dev/null \
    || apk add --no-cache gettext 2>/dev/null || true
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
