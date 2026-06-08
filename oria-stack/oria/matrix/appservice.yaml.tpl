id: oria_appservice
url: http://backend:8000/_matrix/app/v1
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
sender_localpart: oriabot
namespaces:
  users:
    - exclusive: true
      regex: "@oria_.*:${MATRIX_SERVER_NAME}"
  rooms:
    - exclusive: false
      regex: "!.*:${MATRIX_SERVER_NAME}"
  aliases:
    - exclusive: true
      regex: "#oria_.*:${MATRIX_SERVER_NAME}"
rate_limited: false
