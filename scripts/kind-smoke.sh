#!/usr/bin/env bash
# Kind smoke for the chart; asserts in the `step` lines. Deletes the cluster on exit;
# KEEP_CLUSTER=1 keeps it (kubeconfig path printed) and a rerun reuses it.
set -euo pipefail
cd "$(dirname "$0")/.."

CLUSTER=${CLUSTER:-optifuel-smoke}
KEDA_VERSION=2.21.0
# Updated by hand: Dependabot has no shell updater.
NODE_IMAGE=kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5
NS=optifuel
CHART=deploy/helm/optifuel
API=http://localhost:18000
STUB=http://localhost:18080
# Own kubeconfig: the user's current context stays untouched.
export KUBECONFIG="${TMPDIR:-/tmp}/optifuel-$CLUSTER.kubeconfig"

for tool in docker kind helm kubectl curl jq openssl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 1; }
done

forwards=()
finish() {
  local status=$?
  # Guarded: bash 3.2 (macOS) calls an empty array unbound under `set -u`.
  if ((${#forwards[@]})); then kill "${forwards[@]}" 2>/dev/null || true; fi
  if ((status != 0)); then
    kubectl -n "$NS" get pods -o wide || true
    kubectl -n "$NS" logs -l app.kubernetes.io/component=worker-abc --tail=20 || true
  fi
  if [[ ${KEEP_CLUSTER:-} == 1 ]]; then
    echo "cluster kept: KUBECONFIG=$KUBECONFIG"
  else
    kind delete cluster --name "$CLUSTER"
  fi
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
  # Fully qualified: KEDA's operator reads this URL too, from its own namespace.
  kubectl -n "$NS" create secret generic optifuel \
    --from-literal=database-url="postgresql://optifuel:$password@optifuel-postgres.$NS.svc:5432/optifuel?sslmode=disable" \
    --from-literal=postgres-password="$password" \
    --from-literal=weather-token=kind-token
fi
helm upgrade --install optifuel "$CHART" --namespace "$NS" -f "$CHART/values-kind.yaml" \
  --set image.tag="$tag" \
  --set-file tenants.ABC.model=models/ABC/2026-09-30.json \
  --set-file tenants.XYZ.model=models/XYZ/2026-09-30.json \
  --set-file weatherStub.mapping=deploy/weather-stub/mappings/winds.json \
  --wait --timeout 5m

kubectl -n "$NS" port-forward svc/optifuel-api 18000:8000 >/dev/null &
forwards+=($!)
kubectl -n "$NS" port-forward svc/optifuel-weather 18080:8080 >/dev/null &
forwards+=($!)
curl --retry 20 --retry-all-errors --retry-delay 1 -fsS "$API/ready" >/dev/null
curl --retry 20 --retry-all-errors --retry-delay 1 -fsS "$STUB/__admin/health" >/dev/null

# In-envelope plan; the flight id makes each submission a new job, not a duplicate.
submit() {
  curl -fsS -H 'X-Airline: ABC' -H 'Content-Type: application/json' "$API/v1/jobs" -d '{
    "type": "fuel_estimate",
    "payload": {"airline": "ABC", "aircraft_type": "B777", "registration": "EC-ABC",
                "flight_id": '"$1"', "route": [
                  {"latitude": 41.3, "longitude": 2.1, "speed": 200, "altitude": 5000},
                  {"latitude": 41.8, "longitude": 3.0, "speed": 180, "altitude": 4000}]}}' |
    jq -r .id
}

# wait_for ID STATUS SECONDS: prints the job view once it has STATUS; a `failed` job fails.
wait_for() {
  local id=$1 want=$2 deadline=$((SECONDS + $3)) view status
  while ((SECONDS < deadline)); do
    view=$(curl -fsS -H 'X-Airline: ABC' "$API/v1/jobs/$id")
    status=$(jq -r .status <<<"$view")
    if [[ $status == "$want" ]]; then
      echo "$view"
      return
    fi
    if [[ $status == failed ]]; then
      echo "job $id failed: $view" >&2
      return 1
    fi
    sleep 0.5
  done
  echo "job $id not $want after $3 s: $view" >&2
  return 1
}

flight=$(date +%s)

step "submit a plan, poll until succeeded"
id=$(submit "$flight")
wait_for "$id" succeeded 60 | jq -c '{id, status, attempts, result}'

step "KEDA scales worker-abc past 1 replica"
# 12 clears the HPA 10% band (target+1 does not). A 60s delay exceeds the 5s client timeout, so
# retries keep jobs todo until the HPA syncs; reset once spec>1, before the third attempt fails.
n_jobs=12  # keda.targetQueueLength (10) + HPA 10% tolerance + 1; bump with values-kind.yaml
curl -fsS -X POST "$STUB/__admin/settings" -d '{"fixedDelay": 60000}' >/dev/null
scale_ids=()
for ((i = 1; i <= n_jobs; i++)); do
  # flight+1 is the pod-kill job below.
  scale_ids+=("$(submit "$((flight + 1 + i))")")
done
scale_deadline=$((SECONDS + 180))
ready=0
spec=0
delay_reset=0
while ((SECONDS < scale_deadline)); do
  spec=$(kubectl -n "$NS" get deployment optifuel-worker-abc -o jsonpath='{.spec.replicas}')
  spec=${spec:-0}
  ready=$(kubectl -n "$NS" get deployment optifuel-worker-abc -o jsonpath='{.status.readyReplicas}')
  ready=${ready:-0}
  # Scale-down waits out the HPA stabilization window, so the extra replica stays
  # while its pod starts.
  if ((delay_reset == 0 && spec > 1)); then
    curl -fsS -X POST "$STUB/__admin/settings" -d '{"fixedDelay": 0}' >/dev/null
    delay_reset=1
  fi
  ((ready > 1)) && break
  sleep 2
done
echo "worker-abc readyReplicas=$ready specReplicas=$spec after $n_jobs jobs (target 10)"
((ready > 1)) || { echo "worker-abc did not scale past 1 replica" >&2; exit 1; }
if ((delay_reset == 0)); then
  curl -fsS -X POST "$STUB/__admin/settings" -d '{"fixedDelay": 0}' >/dev/null
fi
for id in "${scale_ids[@]}"; do
  wait_for "$id" succeeded 180 >/dev/null
done

step "kill the worker mid-job, job still succeeds"
# The stub answers after 3 s (client timeout 5 s) and the pod gets 1 s to stop, so the job dies
# running. Its heartbeat goes stale after 30 s; the cleanup CronJob's job requeues it.
curl -fsS -X POST "$STUB/__admin/settings" -d '{"fixedDelay": 3000}' >/dev/null
id=$(submit "$((flight + 1))")
wait_for "$id" running 30 >/dev/null
kubectl -n "$NS" delete pod -l app.kubernetes.io/component=worker-abc --grace-period=1
curl -fsS -X POST "$STUB/__admin/settings" -d '{"fixedDelay": 0}' >/dev/null
sleep 35
kubectl -n "$NS" create job "optifuel-cleanup-$flight" --from=cronjob/optifuel-cleanup
kubectl -n "$NS" wait --for=condition=complete "job/optifuel-cleanup-$flight" --timeout=2m
view=$(wait_for "$id" succeeded 60)
jq -c '{id, status, attempts}' <<<"$view"
# Two attempts: the killed one and the requeued one. One would mean the pod finished it.
[[ $(jq .attempts <<<"$view") == 2 ]] || { echo "expected 2 attempts: $view" >&2; exit 1; }

step "keda.enabled=false: workers run their min replicas"
helm upgrade optifuel "$CHART" --namespace "$NS" --reuse-values \
  --set keda.enabled=false --set worker.minReplicas=2 --wait --timeout 5m
for airline in abc xyz; do
  ready=$(kubectl -n "$NS" get deployment "optifuel-worker-$airline" -o jsonpath='{.status.readyReplicas}')
  [[ $ready == 2 ]] || { echo "worker-$airline: $ready ready replicas, want 2" >&2; exit 1; }
done
if kubectl -n "$NS" get scaledobjects -o name | grep -q .; then
  echo "ScaledObjects left with KEDA off" >&2
  exit 1
fi

step "smoke passed"
