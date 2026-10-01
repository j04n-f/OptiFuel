#!/usr/bin/env bash
# Kind dev environment: same install as kind-smoke.sh (cluster, KEDA, image, chart with in-cluster
# Postgres and weather stub), then port-forwards it to localhost and blocks until Ctrl-C. The
# cluster stays; a rerun reuses it and rolls the pods onto a rebuilt image. `kind-dev.sh down`
# deletes it.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=${CLUSTER:-optifuel-dev}
KEDA_VERSION=2.21.0
# Updated by hand, together with kind-smoke.sh: Dependabot has no shell updater.
NODE_IMAGE=kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
NS=optifuel
CHART=deploy/helm/optifuel
API_PORT=${API_PORT:-18000}
STUB_PORT=${STUB_PORT:-18080}
PG_PORT=${PG_PORT:-15432}
# Own kubeconfig: the user's current context stays untouched.
export KUBECONFIG="${TMPDIR:-/tmp}/optifuel-$CLUSTER.kubeconfig"

if [[ ${1:-} == down ]]; then
  kind delete cluster --name "$CLUSTER"
  exit
fi

for tool in docker kind helm kubectl curl openssl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }
done

forwards=()
finish() {
  # Guarded: bash 3.2 (macOS) calls an empty array unbound under `set -u`.
  if ((${#forwards[@]})); then kill "${forwards[@]}" 2>/dev/null || true; fi
  echo "port-forwards stopped; cluster kept: KUBECONFIG=$KUBECONFIG ($0 down deletes it)"
}
trap finish EXIT

step() { printf '\n==> %s\n' "$*"; }

step "cluster $CLUSTER"
if kind get clusters | grep -qx "$CLUSTER"; then
  kind export kubeconfig --name "$CLUSTER"
else
  kind create cluster --name "$CLUSTER" --image "$NODE_IMAGE" --wait 2m
fi

step "KEDA $KEDA_VERSION"
helm upgrade --install keda keda --repo https://kedacore.github.io/charts --version "$KEDA_VERSION" \
  --namespace keda --create-namespace --wait --timeout 5m

step "image"
docker build -t optifuel:kind .
# Tag by content: a rebuilt image changes the pod spec, so a rerun rolls the pods.
tag=kind-$(docker image inspect -f '{{.Id}}' optifuel:kind | cut -c8-19)
docker tag optifuel:kind "optifuel:$tag"
kind load docker-image "optifuel:$tag" --name "$CLUSTER"

step "chart"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
# Created once: Postgres keeps the password it was initialised with.
if ! kubectl -n "$NS" get secret optifuel >/dev/null 2>&1; then
  password=$(openssl rand -hex 16)
  keda_password=$(openssl rand -hex 16)
  # Fully qualified: KEDA's operator reads its URL from its own namespace.
  pg=optifuel-postgres.$NS.svc:5432/optifuel?sslmode=disable
  kubectl -n "$NS" create secret generic optifuel \
    --from-literal=database-url="postgresql://optifuel:$password@$pg" \
    --from-literal=keda-database-url="postgresql://keda:$keda_password@$pg" \
    --from-literal=postgres-password="$password" \
    --from-literal=keda-password="$keda_password" \
    --from-literal=weather-token=kind-token
fi
helm upgrade --install optifuel "$CHART" --namespace "$NS" -f "$CHART/values-kind.yaml" \
  --set image.tag="$tag" \
  --set-file tenants.ABC.model=models/ABC/2026-09-30.json \
  --set-file tenants.XYZ.model=models/XYZ/2026-09-30.json \
  --set-file weatherStub.mapping=deploy/weather-stub/mappings/winds.json \
  --wait --timeout 5m

step "port-forwards"
kubectl -n "$NS" port-forward svc/optifuel-api "$API_PORT:8000" >/dev/null &
forwards+=($!)
kubectl -n "$NS" port-forward svc/optifuel-weather "$STUB_PORT:8080" >/dev/null &
forwards+=($!)
kubectl -n "$NS" port-forward svc/optifuel-postgres "$PG_PORT:5432" >/dev/null &
forwards+=($!)
curl --retry 20 --retry-all-errors --retry-delay 1 -fsS "http://localhost:$API_PORT/ready" >/dev/null
curl --retry 20 --retry-all-errors --retry-delay 1 -fsS "http://localhost:$STUB_PORT/__admin/health" >/dev/null
password=$(kubectl -n "$NS" get secret optifuel -o jsonpath='{.data.postgres-password}' | base64 -d)

cat <<EOF

page + API      http://localhost:$API_PORT  (X-Airline: ABC or XYZ)
weather stub    http://localhost:$STUB_PORT/__admin
postgres        OPTIFUEL_DATABASE_URL=postgresql://optifuel:$password@localhost:$PG_PORT/optifuel?sslmode=disable
kubectl         KUBECONFIG=$KUBECONFIG kubectl -n $NS get pods

Ctrl-C stops the port-forwards; the cluster stays.
EOF
wait "${forwards[@]}"
