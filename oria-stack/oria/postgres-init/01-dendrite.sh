#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE dendrite;
    GRANT ALL PRIVILEGES ON DATABASE dendrite TO $POSTGRES_USER;
EOSQL
