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

# --- Application secrets ---------------------------------------------------
# Only a blank value is generated, so an existing install keeps its secrets.
# Each value is captured in a variable first: with `set -e`, a failed
# generator then stops the script instead of writing a blank value.

if [[ -z "$(dotenv_value SECRET_KEY || true)" ]]; then
    new_value="$(generate_secret)"
    set_dotenv_value SECRET_KEY "$new_value"
    echo "Created SECRET_KEY in $ENV_FILE."
else
    echo "SECRET_KEY is already set in $ENV_FILE."
fi

if [[ -z "$(dotenv_value INTERNAL_API_KEY || true)" ]]; then
    new_value="$(generate_secret)"
    set_dotenv_value INTERNAL_API_KEY "$new_value"
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

if [[ -z "$(dotenv_value PROVIDER_AUTH_ENCRYPTION_KEY || true)" ]]; then
    new_value="$(generate_fernet_key)"
    set_dotenv_value PROVIDER_AUTH_ENCRYPTION_KEY "$new_value"
    echo "Created PROVIDER_AUTH_ENCRYPTION_KEY in $ENV_FILE."
else
    echo "PROVIDER_AUTH_ENCRYPTION_KEY is already set in $ENV_FILE."
fi

# --- Infrastructure passwords (FerretDB/Postgres, MinIO, Redis) -------------
# Same rule: only a blank value is generated. Alphanumeric only, because these
# are interpolated into connection URLs and redis-server's command line.
generate_password() {
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import secrets, string; a = string.ascii_letters + string.digits; print("".join(secrets.choice(a) for _ in range(32)))'; then
        return
    fi

    if command -v openssl >/dev/null 2>&1 && openssl rand -hex 16; then
        return
    fi

    fail "Could not generate a password. Install python3 or openssl, or set passwords manually in .env."
}

# Compose resolves the project name from the shell first, then from .env, then
# from the folder name, and normalises it. Mirror that, so the volume check
# below looks at the volume Compose will actually mount.
compose_project_name() {
    local name="${COMPOSE_PROJECT_NAME:-}"
    [[ -n "$name" ]] || name="$(dotenv_value COMPOSE_PROJECT_NAME || true)"
    [[ -n "$name" ]] || name="$(basename "$ROOT_DIR")"
    printf '%s\n' "$name" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-'
}

# Postgres applies its password only when its data volume is first created,
# and MinIO's data is tied to the root credentials it was set up with. A new
# password against an existing volume would lock the stack out of its own
# data, so refuse to generate one when the volume exists. If Docker is
# installed but not answering, the volume cannot be checked, so refuse too --
# otherwise the password written now would be "already set" on the next run
# and the check would never happen.
refuse_if_volume_exists() {
    local key=$1
    local volume=$2
    local project

    command -v docker >/dev/null 2>&1 || return 0   # no Docker: no volumes yet

    docker info >/dev/null 2>&1 || fail "$key is blank in $ENV_FILE, but Docker is not responding, so the script cannot check for an existing '$volume' volume. Start Docker (or fix access to its socket) and re-run, or set $key in $ENV_FILE yourself."

    project="$(compose_project_name)"
    if [[ -n "$(docker volume ls -q \
            --filter "label=com.docker.compose.project=$project" \
            --filter "label=com.docker.compose.volume=$volume")" ]] \
        || docker volume inspect "${project}_${volume}" >/dev/null 2>&1; then
        fail "$key is blank in $ENV_FILE, but volume '${project}_${volume}' already exists and keeps the password it was created with. Put that password in $ENV_FILE (the old default was $3), or remove the volume if its data is disposable."
    fi
}

if [[ -z "$(dotenv_value MONGODB_PASSWORD || true)" ]]; then
    refuse_if_volume_exists MONGODB_PASSWORD voicera_oss_ferretdb_postgres_data admin123
    new_value="$(generate_password)"
    set_dotenv_value MONGODB_PASSWORD "$new_value"
    echo "Created MONGODB_PASSWORD in $ENV_FILE."
else
    echo "MONGODB_PASSWORD is already set in $ENV_FILE."
fi

minio_password="$(dotenv_value MINIO_ROOT_PASSWORD || true)"
if [[ -z "$minio_password" ]]; then
    # An .env that only has the application half set already knows the password.
    minio_password="$(dotenv_value MINIO_SECRET_KEY || true)"
    if [[ -z "$minio_password" ]]; then
        refuse_if_volume_exists MINIO_ROOT_PASSWORD voicera_oss_minio_data minioadmin123
        minio_password="$(generate_password)"
        echo "Created MINIO_ROOT_PASSWORD in $ENV_FILE."
    else
        echo "Set MINIO_ROOT_PASSWORD to match MINIO_SECRET_KEY."
    fi
    set_dotenv_value MINIO_ROOT_PASSWORD "$minio_password"
else
    echo "MINIO_ROOT_PASSWORD is already set in $ENV_FILE."
fi
# The applications authenticate to MinIO with MINIO_SECRET_KEY; it must match.
if [[ -z "$(dotenv_value MINIO_SECRET_KEY || true)" ]]; then
    set_dotenv_value MINIO_SECRET_KEY "$minio_password"
    echo "Set MINIO_SECRET_KEY to match MINIO_ROOT_PASSWORD."
fi

# Redis keeps no credentials on disk, so a new password needs no volume check.
redis_password="$(dotenv_value REDIS_PASSWORD || true)"
if [[ -z "$redis_password" ]]; then
    redis_password="$(generate_password)"
    set_dotenv_value REDIS_PASSWORD "$redis_password"
    echo "Created REDIS_PASSWORD in $ENV_FILE."
else
    echo "REDIS_PASSWORD is already set in $ENV_FILE."
fi
# Compose rebuilds REDIS_URL for the containers; this is the host-side value
# used when running the apps from source.
if [[ -z "$(dotenv_value REDIS_URL || true)" ]]; then
    set_dotenv_value REDIS_URL "redis://:${redis_password}@localhost:6379"
    echo "Set REDIS_URL from REDIS_PASSWORD."
fi

# --- Warn about publicly known values ----------------------------------------
# Installs created before .env.example was blanked still carry the template's
# fixed secrets, and older defaults for the passwords. Values already set are
# never changed by this script, so say so loudly. The old secrets are compared
# by SHA-256 so they are not written into this file again.
sha256_of() {
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | cut -d' ' -f1
    fi
}

public_values=()
for key in SECRET_KEY INTERNAL_API_KEY PROVIDER_AUTH_ENCRYPTION_KEY; do
    value="$(dotenv_value "$key" || true)"
    [[ -n "$value" ]] || continue
    case "$(printf '%s' "$value" | sha256_of)" in
        5c9ef729ebf62d5baf2c389ac646c0f9aa1ba15398dd1f21a21ff8013a36d608 | \
        ea48197c693ea1ce998631151543a661b021321145ca4a943701c34a4a80d313 | \
        5f209954d0274329add07ea8e8f7feefdf8894e34f25bc355f6385e591e9cca3)
            public_values+=("$key")
            ;;
    esac
done
[[ "$(dotenv_value MONGODB_PASSWORD || true)" == "admin123" ]] && public_values+=(MONGODB_PASSWORD)
[[ "$(dotenv_value MINIO_ROOT_PASSWORD || true)" == "minioadmin123" ]] && public_values+=(MINIO_ROOT_PASSWORD)
[[ "$(dotenv_value MINIO_SECRET_KEY || true)" == "minioadmin123" ]] && public_values+=(MINIO_SECRET_KEY)
[[ "$(dotenv_value REDIS_PASSWORD || true)" == "redissecret" ]] && public_values+=(REDIS_PASSWORD)

if (( ${#public_values[@]} > 0 )); then
    {
        echo ""
        echo "WARNING: $ENV_FILE uses publicly known values for: ${public_values[*]}"
        echo "  These came from an older .env.example and are visible to anyone on GitHub."
        echo "  This script never changes values that are already set. Rotate them before"
        echo "  exposing this stack -- see docs/developer/reference/environment-variables.md"
        echo "  (\"Installs created before the secrets were blanked\")."
        echo ""
    } >&2
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
