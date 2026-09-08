#!/usr/bin/env bash
# Start the Voicera Docker stack (FerretDB + API on :8000).
# Ensures a root .env with required secrets, then runs docker compose up.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env"

fail() {
    echo "Error: $*" >&2
    exit 1
}

generate_secret() {
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; then
        return
    fi

    if command -v openssl >/dev/null 2>&1 && openssl rand -base64 32 | tr -d '=\n+/'; then
        return
    fi

    fail "Could not generate a secret. Install python3 or openssl, or set secrets manually in .env."
}

dotenv_value() {
    local key=$1
    local line

    [[ -f "$ENV_FILE" ]] || return 1

    while IFS= read -r line || [[ -n "$line" ]]; do
        case "$line" in
            "$key"=*)
                printf '%s\n' "${line#*=}"
                return 0
                ;;
        esac
    done < "$ENV_FILE"

    return 1
}

set_dotenv_value() {
    local key=$1
    local value=$2
    local tmp_file="${ENV_FILE}.tmp.$$"
    local line
    local updated=false

    if [[ -f "$ENV_FILE" ]]; then
        while IFS= read -r line || [[ -n "$line" ]]; do
            case "$line" in
                "$key"=*)
                    printf '%s=%s\n' "$key" "$value"
                    updated=true
                    ;;
                *)
                    printf '%s\n' "$line"
                    ;;
            esac
        done < "$ENV_FILE" > "$tmp_file"

        if [[ "$updated" != "true" ]]; then
            printf '%s=%s\n' "$key" "$value" >> "$tmp_file"
        fi

        mv "$tmp_file" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" > "$ENV_FILE"
    fi
}

[[ -f docker-compose.yaml ]] || fail "docker-compose.yaml not found at repo root. Re-run from the Voicera checkout."

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f .env.example ]]; then
        cp .env.example "$ENV_FILE"
        echo "Created $ENV_FILE from .env.example."
    else
        touch "$ENV_FILE"
        echo "Created empty $ENV_FILE."
    fi
fi

existing_secret="$(dotenv_value SECRET_KEY || true)"
if [[ -z "$existing_secret" ]]; then
    set_dotenv_value SECRET_KEY "$(generate_secret)"
    echo "Created SECRET_KEY in $ENV_FILE."
else
    echo "SECRET_KEY is already set in $ENV_FILE."
fi

existing_api_key="$(dotenv_value INTERNAL_API_KEY || true)"
if [[ -z "$existing_api_key" ]]; then
    set_dotenv_value INTERNAL_API_KEY "$(generate_secret)"
    echo "Created INTERNAL_API_KEY in $ENV_FILE."
else
    echo "INTERNAL_API_KEY is already set in $ENV_FILE."
fi

generate_fernet_key() {
    if command -v python3 >/dev/null 2>&1 && python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'; then
        return
    fi
    fail "Could not generate PROVIDER_AUTH_ENCRYPTION_KEY. Install python3 + cryptography, or set it manually in .env (Fernet.generate_key())."
}

existing_enc_key="$(dotenv_value PROVIDER_AUTH_ENCRYPTION_KEY || true)"
if [[ -z "$existing_enc_key" ]]; then
    set_dotenv_value PROVIDER_AUTH_ENCRYPTION_KEY "$(generate_fernet_key)"
    echo "Created PROVIDER_AUTH_ENCRYPTION_KEY in $ENV_FILE."
else
    echo "PROVIDER_AUTH_ENCRYPTION_KEY is already set in $ENV_FILE."
fi

echo ""
echo "This will run:"
echo "  docker compose -f docker-compose.yaml up --build -d"
echo ""
api_port="$(dotenv_value API_HOST_PORT || true)"
api_port="${api_port:-8000}"
ferret_port="$(dotenv_value FERRETDB_HOST_PORT || true)"
ferret_port="${ferret_port:-27018}"
minio_api_port="$(dotenv_value MINIO_API_PORT || true)"
minio_api_port="${minio_api_port:-9000}"
minio_console_port="$(dotenv_value MINIO_CONSOLE_PORT || true)"
minio_console_port="${minio_console_port:-9001}"
runtime_port="$(dotenv_value RUNTIME_HOST_PORT || true)"
runtime_port="${runtime_port:-7860}"
frontend_port="$(dotenv_value FRONTEND_HOST_PORT || true)"
frontend_port="${frontend_port:-3000}"

echo "  Frontend:       http://localhost:${frontend_port}"
echo "  API:            http://localhost:${api_port}"
echo "  OpenAPI docs:   http://localhost:${api_port}/docs"
echo "  Runtime:        http://localhost:${runtime_port}"
echo "  FerretDB:       localhost:${ferret_port}"
echo "  MinIO API:      http://localhost:${minio_api_port}"
echo "  MinIO console:  http://localhost:${minio_console_port}"
echo ""

if [[ ! -t 0 ]]; then
    echo "Non-interactive shell detected; starting without prompt."
else
    read -r -p "Start Voicera now? [Y/n]: " answer
    case "$answer" in
        [Nn]*)
            echo "Voicera was not started."
            exit 0
            ;;
    esac
fi

# Detached by default so the script returns after containers are up.
# Pass extra compose args after -- if needed, e.g. ./scripts/start_docker.sh -- --no-build
docker compose -f docker-compose.yaml up --build -d "$@"

echo ""
echo "Voicera is starting in the background."
echo "  Status:  docker compose -f docker-compose.yaml ps"
echo "  Logs:    docker compose -f docker-compose.yaml logs -f api runtime frontend"
echo "  Stop:    ./scripts/stop-application-services.sh"
