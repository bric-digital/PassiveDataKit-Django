#!/bin/bash

set -euo pipefail

SSMTP_CONFIG="/dev/shm/ssmtp.conf"
CRON_ENV="/dev/shm/cron.env"

write_shell_var() {
  local name="$1"
  local value="${2-}"

  printf "export %s=%q\n" "$name" "$value" >> "$CRON_ENV"
}

cat > "$SSMTP_CONFIG" <<EOF
root=$CRON_MAIL_RECIPIENT
mailhub=$CRON_MAIL_SERVER
rewriteDomain=$CRON_MAIL_DOMAIN
hostname=$CRON_SENDER_HOSTNAME
UseTLS=Yes
UseSTARTTLS=Yes
FromLineOverride=No
AuthUser=$CRON_MAIL_USERNAME
AuthPass=$CRON_MAIL_PASSWORD
EOF

chmod 600 "$SSMTP_CONFIG"
ln -sf "$SSMTP_CONFIG" /etc/ssmtp/ssmtp.conf

: > "$CRON_ENV"
chmod 600 "$CRON_ENV"

write_shell_var "DJANGO_HOST" "${DJANGO_HOST-}"
write_shell_var "DJANGO_WEB_PORT" "${DJANGO_WEB_PORT-}"
write_shell_var "DJANGO_SECRET_KEY" "${DJANGO_SECRET_KEY-}"
write_shell_var "DJANGO_ADMIN_NAME" "${DJANGO_ADMIN_NAME-}"
write_shell_var "DJANGO_ADMIN_EMAIL" "${DJANGO_ADMIN_EMAIL-}"
write_shell_var "DJANGO_DEBUG" "${DJANGO_DEBUG-}"
write_shell_var "DJANGO_ALLOWED_HOST" "${DJANGO_ALLOWED_HOST-}"
write_shell_var "PROJECT_HOSTNAME" "${PROJECT_HOSTNAME-}"

write_shell_var "PG_DB" "${PG_DB-}"
write_shell_var "PG_SERVER" "${PG_SERVER-}"
write_shell_var "PG_USER" "${PG_USER-}"
write_shell_var "AWS_REGION" "${AWS_REGION-}"
write_shell_var "ACCOUNT_ID" "${ACCOUNT_ID-}"

write_shell_var "CRON_MAIL_RECIPIENT" "${CRON_MAIL_RECIPIENT-}"
write_shell_var "CRON_MAIL_DOMAIN" "${CRON_MAIL_DOMAIN-}"
write_shell_var "CRON_SENDER_HOSTNAME" "${CRON_SENDER_HOSTNAME-}"
write_shell_var "CRON_MAIL_SERVER" "${CRON_MAIL_SERVER-}"
write_shell_var "CRON_MAIL_USERNAME" "${CRON_MAIL_USERNAME-}"
write_shell_var "CRON_MAIL_PASSWORD" "${CRON_MAIL_PASSWORD-}"

cron && tail -f /var/log/cron.log
