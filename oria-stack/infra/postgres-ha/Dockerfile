FROM postgres:16-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-psycopg2 \
    && pip3 install --no-cache-dir --break-system-packages "patroni[etcd3]" \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/postgresql/wal_archive /etc/patroni \
    && chown -R postgres:postgres /var/lib/postgresql/wal_archive /etc/patroni

USER postgres
EXPOSE 5432 8008
ENTRYPOINT ["patroni"]
CMD ["/etc/patroni/patroni.yml"]
