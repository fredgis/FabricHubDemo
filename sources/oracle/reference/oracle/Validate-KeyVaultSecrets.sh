#!/usr/bin/env bash
set -euo pipefail

KEY_VAULT_NAME="${1:?Key Vault name is required}"
token="$(curl --fail --silent --show-error \
    --header Metadata:true \
    'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2019-08-01&resource=https%3A%2F%2Fvault.azure.net' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"

secrets=(
    demo-windows-admin-password
    demo-oracle-sys-password
    demo-schema-password
    demo-mirror-password
    demo-gateway-recovery-key
    demo-linux-ssh-private-key
    demo-gateway-app-id
    demo-gateway-app-client-secret
)

for secret in "${secrets[@]}"; do
    status="$(curl --silent --show-error \
        --output /dev/null \
        --write-out '%{http_code}' \
        --header "Authorization: Bearer ${token}" \
        "https://${KEY_VAULT_NAME}.vault.azure.net/secrets/${secret}?api-version=7.4")"
    if [[ "$status" != "200" ]]; then
        echo "SECRET=${secret}|STATUS=${status}" >&2
        exit 1
    fi
    echo "SECRET=${secret}|STATUS=present"
done
