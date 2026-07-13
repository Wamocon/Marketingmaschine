#!/bin/sh
set -eu
umask 077

data_dir="${MARKETING_MACHINE_DATA_DIR:-/data}"

case "$data_dir" in
  /data|/data/*) ;;
  *)
    echo "MARKETING_MACHINE_DATA_DIR must stay below /data inside the container" >&2
    exit 64
    ;;
esac

mkdir -p "$data_dir"
chown -R marketing:marketing "$data_dir"
find "$data_dir" -type d -exec chmod 0700 {} +
find "$data_dir" -type f -exec chmod 0600 {} +

# Docker Compose implements file-backed secrets as root-owned bind mounts on
# Linux. Copy only the two agent secrets into a private tmpfs-backed runtime
# directory before dropping privileges; never copy them into /data or logs.
runtime_secret_dir=/run/wamocon-agent-secrets
install -d -m 0700 -o marketing -g marketing "$runtime_secret_dir"

copy_agent_secret() {
  source_path="$1"
  target_path="$2"
  label="$3"
  if [ ! -r "$source_path" ] || [ ! -s "$source_path" ]; then
    echo "$label secret is missing or unreadable" >&2
    exit 78
  fi
  cp "$source_path" "$target_path"
  chown marketing:marketing "$target_path"
  chmod 0400 "$target_path"
}

if [ -n "${MARKETING_MACHINE_MUTATION_TOKEN_FILE:-}" ]; then
  copy_agent_secret \
    "$MARKETING_MACHINE_MUTATION_TOKEN_FILE" \
    "$runtime_secret_dir/mutation_token" \
    "mutation token"
  MARKETING_MACHINE_MUTATION_TOKEN_FILE="$runtime_secret_dir/mutation_token"
  export MARKETING_MACHINE_MUTATION_TOKEN_FILE
fi

if [ -n "${MARKETING_MACHINE_EDGE_ATTESTATION_FILE:-}" ]; then
  copy_agent_secret \
    "$MARKETING_MACHINE_EDGE_ATTESTATION_FILE" \
    "$runtime_secret_dir/edge_attestation" \
    "edge attestation"
  MARKETING_MACHINE_EDGE_ATTESTATION_FILE="$runtime_secret_dir/edge_attestation"
  export MARKETING_MACHINE_EDGE_ATTESTATION_FILE
fi

exec setpriv \
  --no-new-privs \
  su-exec marketing:marketing \
  "$@"
