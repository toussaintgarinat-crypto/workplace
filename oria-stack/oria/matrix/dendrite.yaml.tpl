version: 2

global:
  server_name: ${MATRIX_SERVER_NAME}
  private_key: /var/dendrite/keys/matrix_key.pem
  key_validity_period: 168h0m0s

  database:
    connection_string: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/dendrite?sslmode=disable
    max_open_conns: 10
    max_idle_conns: 2
    conn_max_lifetime: 0

  jetstream:
    storage_path: /var/dendrite/nats

  cache:
    max_size_estimated: 512mb
    max_age: 1h

  report_stats:
    enabled: false

  trusted_id_servers:
    - matrix.org

app_service_api:
  config_files:
    - /etc/dendrite/appservice.yaml

client_api:
  registration_disabled: ${MATRIX_REGISTRATION_DISABLED}
  registration_shared_secret: ${MATRIX_REGISTRATION_SHARED_SECRET}

media_api:
  base_path: /var/dendrite/media
  max_file_size_bytes: 10485760
  dynamic_thumbnails: false

sync_api:
  search:
    enabled: false

user_api:
  bcrypt_cost: 10

logging:
  - type: std
    level: warn
    params:
      colour: false
