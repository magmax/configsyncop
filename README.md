# Kubernetes Configuration Sync Operator

An operator to safely restart pods when configuration changes.

## How it works

Configsyncop will watch your configmaps and secrets.
If any annotated secret/configmap is modified, it will perform a rollout for any
deployment, daemonset or statefulset using that secret/configmap.

## Installation

1. Install RBAC permissions: `kubectl apply -f rbac.yaml`
1. Install main operator: `kubectl apply -f deployment.yaml`

## Usage

1. Annotate your *configmaps* or *secrets* with `k8s.config.sync.manage: "true"`.


## Examples

The folder `example` contains dummy secrets and configmaps. Just install them:

```
kubectl apply -f example/secret.yaml
kubectl apply -f example/configmap.yaml
```

Then you can install the deployments, daemonsets or statefulsets you want. There
are four flavours:
- _*-env-secret.yaml_: uses the secret as an environment variable.
- _*-volume-secret.yaml_: uses the secret as a volume.
- _*-env-cm.yaml_: uses the configmap as an environment variable.
- _*-volume-cm.yaml_: uses the configmap as a volume.


## Monitoring

Automatically exposes Prometheus metrics on port 9090.
