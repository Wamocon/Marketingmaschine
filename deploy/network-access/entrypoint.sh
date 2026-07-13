#!/bin/sh
set -eu

secret_file="${MARKETING_MUTATION_TOKEN_FILE:-/run/secrets/marketing_mutation_token}"
edge_attestation_file="${MARKETING_EDGE_ATTESTATION_FILE:-/run/secrets/marketing_edge_attestation}"
operator_file="${MARKETING_OPERATOR_HTPASSWD_FILE:-/run/secrets/marketing_operator_htpasswd}"
tls_certificate_file="${MARKETING_TLS_CERTIFICATE_FILE:-/run/secrets/marketing_tls_certificate}"
tls_private_key_file="${MARKETING_TLS_PRIVATE_KEY_FILE:-/run/secrets/marketing_tls_private_key}"
template_file="/etc/wamocon/default.conf.template"
target_file="/etc/nginx/conf.d/default.conf"
allowed_hosts_file="/etc/nginx/conf.d/00-wamocon-allowed-hosts.conf"
allowed_clients_file="/etc/nginx/conf.d/01-wamocon-client-access.conf"

if [ ! -r "$secret_file" ]; then
  echo "marketing mutation token secret is missing or unreadable" >&2
  exit 78
fi

if [ ! -r "$edge_attestation_file" ]; then
  echo "marketing edge attestation secret is missing or unreadable" >&2
  exit 78
fi

if [ ! -r "$operator_file" ] || [ ! -s "$operator_file" ]; then
  echo "marketing operator password file is missing or empty" >&2
  exit 78
fi

if [ ! -r "$tls_certificate_file" ] || [ ! -s "$tls_certificate_file" ] \
  || [ ! -r "$tls_private_key_file" ] || [ ! -s "$tls_private_key_file" ]; then
  echo "marketing TLS certificate or private key is missing" >&2
  exit 78
fi

allowed_hosts="${MARKETING_MACHINE_ALLOWED_HOSTS:-}"
if [ -z "$allowed_hosts" ]; then
  echo "MARKETING_MACHINE_ALLOWED_HOSTS must list the exact TLS hostnames or LAN IP addresses" >&2
  exit 78
fi

# Generate an exact nginx host map. Do not accept wildcard domains, URLs,
# ports, paths, or regex characters. Loopback remains available for local
# health/maintenance traffic, while every LAN authority must be explicit.
umask 077
{
  echo 'map $host $wamocon_allowed_host {'
  echo '  default 0;'
  echo '  localhost 1;'
  echo '  127.0.0.1 1;'
} > "$allowed_hosts_file"

remaining="$allowed_hosts,"
host_count=0
seen_hosts="localhost 127.0.0.1"
while [ -n "$remaining" ]; do
  host="${remaining%%,*}"
  remaining="${remaining#*,}"
  host="$(printf '%s' "$host" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  case "$host" in
    *[!A-Za-z0-9.-]*)
      echo "MARKETING_MACHINE_ALLOWED_HOSTS contains an invalid hostname or IPv4 address" >&2
      exit 78
      ;;
  esac
  host="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"
  if [ -z "$host" ]; then
    echo "MARKETING_MACHINE_ALLOWED_HOSTS contains an empty entry" >&2
    exit 78
  fi
  if ! printf '%s' "$host" | grep -Eq '^([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?)$'; then
    echo "MARKETING_MACHINE_ALLOWED_HOSTS contains an invalid hostname or IPv4 address" >&2
    exit 78
  fi
  case "$host" in
    *..*|.*|*.)
      echo "MARKETING_MACHINE_ALLOWED_HOSTS contains an invalid hostname or IPv4 address" >&2
      exit 78
      ;;
  esac
  case " $seen_hosts " in
    *" $host "*)
      echo "MARKETING_MACHINE_ALLOWED_HOSTS contains a duplicate or reserved loopback entry" >&2
      exit 78
      ;;
  esac
  seen_hosts="$seen_hosts $host"
  # Quoting prevents nginx map keywords such as "default" or "include" from
  # changing the meaning of an otherwise syntactically valid hostname.
  printf '  "%s" 1;\n' "$host" >> "$allowed_hosts_file"
  host_count=$((host_count + 1))
done
echo '}' >> "$allowed_hosts_file"

if [ "$host_count" -lt 1 ]; then
  echo "MARKETING_MACHINE_ALLOWED_HOSTS must contain at least one exact host" >&2
  exit 78
fi

# Generate the network access list from deployment configuration instead of
# embedding workstation DHCP addresses in the public repository. The strict
# character allowlist prevents nginx directive injection; nginx -t below is the
# final authority for IPv4/CIDR syntax and prefix ranges.
allowed_clients="${MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS:-}"
if [ -z "$allowed_clients" ]; then
  echo "MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS must list approved operator IP addresses or CIDRs" >&2
  exit 78
fi

umask 077
echo 'allow 127.0.0.1;' > "$allowed_clients_file"
remaining="$allowed_clients,"
client_count=0
seen_clients="127.0.0.1"
while [ -n "$remaining" ]; do
  client="${remaining%%,*}"
  remaining="${remaining#*,}"
  client="$(printf '%s' "$client" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  case "$client" in
    ""|*[!0-9./]*)
      echo "MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS contains an invalid IPv4 address or CIDR" >&2
      exit 78
      ;;
  esac
  case " $seen_clients " in
    *" $client "*)
      echo "MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS contains a duplicate or reserved loopback entry" >&2
      exit 78
      ;;
  esac
  seen_clients="$seen_clients $client"
  printf 'allow %s;\n' "$client" >> "$allowed_clients_file"
  client_count=$((client_count + 1))
done
echo 'deny all;' >> "$allowed_clients_file"

if [ "$client_count" -lt 1 ]; then
  echo "MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS must contain at least one approved client" >&2
  exit 78
fi

# Accept only named accounts with modern bcrypt or SHA-512 crypt hashes. A
# plaintext/default password file must never make the edge proxy start.
if grep -Ev '^[A-Za-z0-9._-]+:\$(2[aby]|6)\$' "$operator_file" | grep -q .; then
  echo "marketing operator password file contains an invalid account or hash" >&2
  exit 78
fi

operator_count="$(cut -d: -f1 "$operator_file" | sort -u | wc -l | tr -d ' ')"
if [ "$operator_count" -lt 2 ]; then
  echo "at least two distinct named marketing operator accounts are required" >&2
  exit 78
fi

if cut -d: -f1 "$operator_file" | grep -Eiq '^(admin|anonymous|automation|marketing|n8n|operator|service|unknown|user)$'; then
  echo "marketing operator accounts must identify individual people, not generic roles" >&2
  exit 78
fi

token="$(tr -d '\r\n' < "$secret_file")"
case "$token" in
  ""|*[!0-9A-Fa-f]*)
    echo "marketing mutation token must be a non-empty hexadecimal secret" >&2
    exit 78
    ;;
esac

if [ "${#token}" -lt 64 ]; then
  echo "marketing mutation token must contain at least 64 hexadecimal characters" >&2
  exit 78
fi

edge_attestation="$(tr -d '\r\n' < "$edge_attestation_file")"
case "$edge_attestation" in
  ""|*[!0-9A-Fa-f]*)
    echo "marketing edge attestation must be a non-empty hexadecimal secret" >&2
    exit 78
    ;;
esac

if [ "${#edge_attestation}" -lt 64 ]; then
  echo "marketing edge attestation must contain at least 64 hexadecimal characters" >&2
  exit 78
fi

if [ "$edge_attestation" = "$token" ]; then
  echo "marketing edge attestation must not reuse the mutation token" >&2
  exit 78
fi

comfyui_upstream="${MARKETING_COMFYUI_UPSTREAM:-}"
case "$comfyui_upstream" in
  ""|*[!A-Za-z0-9.:-]*)
    echo "MARKETING_COMFYUI_UPSTREAM must be an exact private hostname or IPv4 address plus port" >&2
    exit 78
    ;;
esac
if ! printf '%s' "$comfyui_upstream" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?:[0-9]{1,5}$'; then
  echo "MARKETING_COMFYUI_UPSTREAM must be an exact private hostname or IPv4 address plus port" >&2
  exit 78
fi

umask 077
sed \
  -e "s/__WAMOCON_MUTATION_TOKEN__/$token/g" \
  -e "s/__WAMOCON_EDGE_ATTESTATION__/$edge_attestation/g" \
  -e "s/__WAMOCON_COMFYUI_UPSTREAM__/$comfyui_upstream/g" \
  "$template_file" > "$target_file"
unset token edge_attestation comfyui_upstream

nginx -t
exec nginx -g 'daemon off;'
