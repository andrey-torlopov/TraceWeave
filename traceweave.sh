#!/bin/sh
set -eu
TW_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TW_CALLER_DIR=$(pwd -P)
command -v docker >/dev/null 2>&1 || { echo 'Установите Docker Engine/Desktop с Compose, затем повторите команду.' >&2; exit 1; }
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$TW_SCRIPT_DIR/tools/control.py" "$@"
fi
# A Docker-only host can run the operator CLI in a short-lived tools container.
# This explicitly invoked CLI needs operator-level access to the Docker socket.
if [ -z "${TW_TOOLS_IMAGE:-}" ] && [ -f "$TW_SCRIPT_DIR/releases/tools-image.txt" ]; then
  TW_TOOLS_IMAGE=
  TW_TOOLS_EXTRA=
  {
    IFS= read -r TW_TOOLS_IMAGE || [ -n "$TW_TOOLS_IMAGE" ] || { echo 'Invalid published operator image reference: empty file.' >&2; exit 1; }
    if IFS= read -r TW_TOOLS_EXTRA || [ -n "$TW_TOOLS_EXTRA" ]; then
      echo 'Invalid published operator image reference: expected exactly one line.' >&2; exit 1
    fi
  } < "$TW_SCRIPT_DIR/releases/tools-image.txt"
  TW_TOOLS_REPOSITORY=${TW_TOOLS_IMAGE%@sha256:*}
  TW_TOOLS_DIGEST=${TW_TOOLS_IMAGE##*@sha256:}
  case "$TW_TOOLS_IMAGE" in *@sha256:*) ;; *) echo 'Invalid published operator image reference.' >&2; exit 1;; esac
  case "$TW_TOOLS_REPOSITORY" in ''|*[!a-zA-Z0-9._/:+-]*) echo 'Invalid published operator repository.' >&2; exit 1;; esac
  case "$TW_TOOLS_DIGEST" in ''|*[!a-f0-9]*) echo 'Invalid published operator digest.' >&2; exit 1;; esac
  [ "${#TW_TOOLS_DIGEST}" -eq 64 ] || { echo 'Invalid published operator digest length.' >&2; exit 1; }
fi
TW_TOOLS_IMAGE=${TW_TOOLS_IMAGE:-traceweave/tools:docker-1}
if ! docker image inspect "$TW_TOOLS_IMAGE" >/dev/null 2>&1; then
  case "$TW_TOOLS_IMAGE" in
    *@sha256:*) docker pull "$TW_TOOLS_IMAGE";;
    traceweave/tools:docker-1) docker build -t "$TW_TOOLS_IMAGE" -f "$TW_SCRIPT_DIR/tools/Dockerfile" "$TW_SCRIPT_DIR";;
    *) echo 'TW_TOOLS_IMAGE must be a published immutable digest or the local default tag.' >&2; exit 1;;
  esac
fi
TW_DOCKER_ENDPOINT=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}')
case "$TW_DOCKER_ENDPOINT" in unix://*) TW_SOCKET=${TW_DOCKER_ENDPOINT#unix://};; *) echo 'Docker-only CLI requires a local unix Docker socket.' >&2; exit 1;; esac
TW_RUNTIME_PATH=${TW_RUNTIME_DIR:-$TW_SCRIPT_DIR/runtime}
case "$TW_RUNTIME_PATH" in /*) ;; *) echo 'Docker-only CLI requires an absolute TW_RUNTIME_DIR.' >&2; exit 1;; esac
[ ! -L "$TW_RUNTIME_PATH" ] || { echo 'Runtime must not be a symlink.' >&2; exit 1; }
mkdir -p "$TW_RUNTIME_PATH"
chmod 700 "$TW_RUNTIME_PATH"
TW_RUNTIME_PATH=$(CDPATH= cd -- "$TW_RUNTIME_PATH" && pwd -P)

# Resolve only explicitly used files/checkouts. Keep the original argv for the
# controller, whose relative paths must see the same working directory.
tw_fail() { printf '%s\n' "$1" >&2; exit 1; }
tw_resolve_directory() {
  case "$1" in /*) TW_RESOLVE_PATH=$1;; *) TW_RESOLVE_PATH=$TW_CALLER_DIR/$1;; esac
  [ -d "$TW_RESOLVE_PATH" ] || tw_fail 'Docker-only CLI source directory does not exist.'
  CDPATH= cd -- "$TW_RESOLVE_PATH" && pwd -L
}
tw_check_mount_path() {
  case "$1" in *,*) tw_fail 'Docker-only CLI bind paths cannot contain commas.';; esac
}
tw_git_metadata() {
  if [ -d "$1/.git" ]; then return; fi
  [ -f "$1/.git" ] || tw_fail 'Docker-only build-source requires a Git checkout.'
  TW_GIT_LINE=
  IFS= read -r TW_GIT_LINE < "$1/.git" || [ -n "$TW_GIT_LINE" ]
  case "$TW_GIT_LINE" in 'gitdir: '*) TW_GIT_REFERENCE=${TW_GIT_LINE#gitdir: };; *) tw_fail 'Invalid Git worktree reference.';; esac
  case "$TW_GIT_REFERENCE" in /*) ;; *) TW_GIT_REFERENCE=$1/$TW_GIT_REFERENCE;; esac
  TW_GIT_DIRECTORY=$(tw_resolve_directory "$TW_GIT_REFERENCE")
  [ -f "$TW_GIT_DIRECTORY/commondir" ] || tw_fail 'Docker-only CLI requires standard Git worktree metadata; use host Python for a custom Git directory.'
  TW_GIT_COMMON_REFERENCE=
  IFS= read -r TW_GIT_COMMON_REFERENCE < "$TW_GIT_DIRECTORY/commondir" || [ -n "$TW_GIT_COMMON_REFERENCE" ]
  case "$TW_GIT_COMMON_REFERENCE" in /*) ;; *) TW_GIT_COMMON_REFERENCE=$TW_GIT_DIRECTORY/$TW_GIT_COMMON_REFERENCE;; esac
  TW_GIT_COMMON=$(tw_resolve_directory "$TW_GIT_COMMON_REFERENCE")
  case "$TW_GIT_COMMON" in */.git) ;; *) tw_fail 'Docker-only CLI requires a .git metadata directory; use host Python for a custom worktree.';; esac
  case "$TW_GIT_DIRECTORY" in "$TW_GIT_COMMON"/worktrees/*) ;; *) tw_fail 'Git worktree metadata must belong to the referenced .git directory.';; esac
  [ -d "$TW_GIT_COMMON/objects" ] && [ -d "$TW_GIT_COMMON/refs" ] && [ -f "$TW_GIT_DIRECTORY/HEAD" ] || tw_fail 'Incomplete Git worktree metadata.'
  tw_check_mount_path "$TW_GIT_COMMON"
  printf '%s\n' "$TW_GIT_COMMON"
}

TW_COMMAND=
TW_PENDING_OPTION=
TW_BACKEND_PATH=$TW_SCRIPT_DIR/../TraceWeaveBackend
TW_FRONTEND_PATH=$TW_SCRIPT_DIR/../TraceWeaveFrontend
TW_RELEASE_PATH=
for TW_ARGUMENT in "$@"; do
  if [ -n "$TW_PENDING_OPTION" ]; then
    case "$TW_PENDING_OPTION" in
      --backend-path) TW_BACKEND_PATH=$TW_ARGUMENT;;
      --frontend-path) TW_FRONTEND_PATH=$TW_ARGUMENT;;
      --release) TW_RELEASE_PATH=$TW_ARGUMENT;;
    esac
    TW_PENDING_OPTION=
    continue
  fi
  case "$TW_ARGUMENT" in
    --backend-path=*) TW_BACKEND_PATH=${TW_ARGUMENT#--backend-path=};;
    --frontend-path=*) TW_FRONTEND_PATH=${TW_ARGUMENT#--frontend-path=};;
    --release=*) TW_RELEASE_PATH=${TW_ARGUMENT#--release=};;
    --release|--release-id|--origin|--port|--email|--name|--backup|--smtp-url|--smtp-user|--smtp-from|--backend-path|--frontend-path) TW_PENDING_OPTION=$TW_ARGUMENT;;
    -*) ;;
    *) if [ -z "$TW_COMMAND" ]; then TW_COMMAND=$TW_ARGUMENT; fi;;
  esac
done
[ -z "$TW_PENDING_OPTION" ] || tw_fail 'Docker-only CLI option requires a value.'

TW_BACKEND_MOUNT=
TW_FRONTEND_MOUNT=
TW_BACKEND_GIT_MOUNT=
TW_FRONTEND_GIT_MOUNT=
TW_RELEASE_MOUNT=
if [ "$TW_COMMAND" = build-source ]; then
  TW_BACKEND_MOUNT=$(tw_resolve_directory "$TW_BACKEND_PATH")
  TW_FRONTEND_MOUNT=$(tw_resolve_directory "$TW_FRONTEND_PATH")
  [ -f "$TW_BACKEND_MOUNT/Package.swift" ] && [ -f "$TW_FRONTEND_MOUNT/package-lock.json" ] || tw_fail 'Provide independent backend/frontend source checkouts.'
  tw_check_mount_path "$TW_BACKEND_MOUNT"
  tw_check_mount_path "$TW_FRONTEND_MOUNT"
  TW_BACKEND_GIT_MOUNT=$(tw_git_metadata "$TW_BACKEND_MOUNT")
  TW_FRONTEND_GIT_MOUNT=$(tw_git_metadata "$TW_FRONTEND_MOUNT")
fi
if [ -n "$TW_RELEASE_PATH" ]; then
  case "$TW_RELEASE_PATH" in /*) TW_RELEASE_INPUT=$TW_RELEASE_PATH;; *) TW_RELEASE_INPUT=$TW_CALLER_DIR/$TW_RELEASE_PATH;; esac
  [ -f "$TW_RELEASE_INPUT" ] || tw_fail 'Explicit release manifest does not exist.'
  TW_RELEASE_PARENT=$(CDPATH= cd -- "$(dirname -- "$TW_RELEASE_INPUT")" && pwd -L)
  TW_RELEASE_ABSOLUTE=$TW_RELEASE_PARENT/$(basename -- "$TW_RELEASE_INPUT")
  tw_check_mount_path "$TW_RELEASE_ABSOLUTE"
  case "$TW_RELEASE_ABSOLUTE" in "$TW_SCRIPT_DIR"/*|"$TW_RUNTIME_PATH"/*) ;; *) TW_RELEASE_MOUNT=$TW_RELEASE_ABSOLUTE;; esac
fi
tw_check_mount_path "$TW_SCRIPT_DIR"
tw_check_mount_path "$TW_RUNTIME_PATH"
tw_check_mount_path "$TW_SOCKET"

TW_TTY=-i
if [ -t 0 ] && [ -t 1 ]; then TW_TTY=-it; fi
tw_run_operator() {
  if [ -n "$TW_BACKEND_MOUNT" ]; then set -- --mount "type=bind,source=$TW_BACKEND_MOUNT,target=$TW_BACKEND_MOUNT,readonly" "$@"; fi
  if [ -n "$TW_FRONTEND_MOUNT" ]; then set -- --mount "type=bind,source=$TW_FRONTEND_MOUNT,target=$TW_FRONTEND_MOUNT,readonly" "$@"; fi
  if [ -n "$TW_BACKEND_GIT_MOUNT" ]; then set -- --mount "type=bind,source=$TW_BACKEND_GIT_MOUNT,target=$TW_BACKEND_GIT_MOUNT,readonly" "$@"; fi
  if [ -n "$TW_FRONTEND_GIT_MOUNT" ] && [ "$TW_FRONTEND_GIT_MOUNT" != "$TW_BACKEND_GIT_MOUNT" ]; then set -- --mount "type=bind,source=$TW_FRONTEND_GIT_MOUNT,target=$TW_FRONTEND_GIT_MOUNT,readonly" "$@"; fi
  if [ -n "$TW_RELEASE_MOUNT" ]; then set -- --mount "type=bind,source=$TW_RELEASE_MOUNT,target=$TW_RELEASE_MOUNT,readonly" "$@"; fi
  exec docker run --rm "$TW_TTY" --entrypoint python3 -e TW_CONTAINER_CONTROL=1 -e TW_OPERATOR_IMAGE="$TW_TOOLS_IMAGE" -e TW_RUNTIME_DIR="$TW_RUNTIME_PATH" -e TW_OPERATOR_UID="$(id -u)" -e TW_OPERATOR_GID="$(id -g)" -e DOCKER_HOST=unix:///var/run/docker.sock --mount "type=bind,source=$TW_SCRIPT_DIR,target=$TW_SCRIPT_DIR" --mount "type=bind,source=$TW_RUNTIME_PATH,target=$TW_RUNTIME_PATH" --mount "type=bind,source=$TW_SOCKET,target=/var/run/docker.sock" -w "$TW_CALLER_DIR" "$@"
}
tw_run_operator "$TW_TOOLS_IMAGE" "$TW_SCRIPT_DIR/tools/control.py" "$@"
