import hashlib
import json
import logging

import kopf
import prometheus_client as prometheus
import pykube

logger = logging.getLogger(__name__)

BASE_ANNOTATION = "k8s.config.sync"
HANDLE_ANNOTATION = f"{BASE_ANNOTATION}.manage"
HASH_ANNOTATION = f"{BASE_ANNOTATION}.hash"

prometheus.start_http_server(9090)

REQUEST_TIME = prometheus.Summary(
    "event_processing_seconds",
    "Time spent processing events",
    ["resource"],
)

CONFIG_CHANGE = prometheus.Counter(
    "config_change",
    "Number of configuration changes",
    ["namespace", "resource", "name"],
)

RESOURCE_PATCH = prometheus.Counter(
    "resource_patch",
    "patches by resource",
    ["namespace", "resource", "name"],
)


class ConfigResource:
    kind = "unknown"

    def __init__(self, body, namespace, name, annotations, **kwargs):
        self.body = body
        self.namespace = namespace
        self.name = name
        self.annotations = annotations
        self._kwargs = kwargs
        self._hash = self._generate_hash(body.get("data"))
        self._annotation = f"{HASH_ANNOTATION}/{self.kind.lower()}-{self.name}"
        CONFIG_CHANGE.labels(namespace, self.kind, name).inc()

    def handle(self):
        with REQUEST_TIME.labels(self.kind).time():
            if not self._must_handle():
                logger.debug(f"{self.kind}/{self.name} not annotated")
                return
            logger.info(
                f"Handler for {self.kind} {self.name} on {self.namespace} -> {self._hash}"
            )
            self._update_template_based_resource(pykube.Deployment, "Deployment")
            self._update_template_based_resource(pykube.DaemonSet, "DaemonSet")
            self._update_template_based_resource(pykube.StatefulSet, "StatefulSet")

    def _must_handle(self):
        if self.annotations.get(HANDLE_ANNOTATION, "").lower() in ("true", "1"):
            return True
        namespace = self._get_namespace()
        if not namespace:
            return False
        annotation = f"{HANDLE_ANNOTATION}/{self.kind}"
        if namespace.annotations.get(annotation) in ("true", "1"):
            return True
        return False

    def _get_namespace(self):
        api = pykube.HTTPClient(pykube.KubeConfig.from_env())
        return pykube.Namespace.objects(api).get_by_name(self.namespace)

    def _generate_hash(self, data):
        json_data = json.dumps(data, sort_keys=True)
        return hashlib.md5(json_data.encode()).hexdigest()

    def _get_template_based_resource(self, PykubeResource, res_name):
        api = pykube.HTTPClient(pykube.KubeConfig.from_env())
        logger.debug(f"Retrieving {res_name} resources")
        for resource in PykubeResource.objects(api).filter(namespace=self.namespace):
            if not self.is_used_by_spec(resource.obj["spec"]["template"]["spec"]):
                logger.debug(
                    f"{res_name} {resource.name} not used by {self.kind}/{self.name}"
                )
                continue
            if resource.annotations.get(self._annotation) == self._hash:
                logger.debug(
                    f"{res_name} {resource.name} is up-to-date:"
                    f" {self._annotation} == {self._hash}"
                )
                continue
            yield resource

    def _update_template_based_resource(self, PykubeResource, res_name):
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            self._annotation: self._hash,
                        }
                    }
                }
            }
        }
        for resource in self._get_template_based_resource(PykubeResource, res_name):
            logger.info(f"Updating {res_name} {resource.name}")
            resource.patch(patch)
            RESOURCE_PATCH.labels(self.namespace, res_name, resource.name).inc()

    def is_used_by_spec(self, spec):
        for container in spec["containers"]:
            for var in container.get("env", []):
                if self.is_used_by_var(var):
                    return True
        for volume in spec.get("volumes", []):
            if self.is_used_by_volume(volume):
                return True
        return False

    def is_used_by_var(self, var):
        raise NotImplementedError()

    def is_used_by_volume(self, volume):
        raise NotImplementedError()


class Secret(ConfigResource):
    kind = "Secret"
    REF = ["", "v1", "secrets"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def is_used_by_var(self, var):
        return var.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == self.name

    def is_used_by_volume(self, volume):
        return volume.get("secret", {}).get("secretName") == self.name


class ConfigMap(ConfigResource):
    kind = "ConfigMap"
    REF = ["", "v1", "configmaps"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def is_used_by_var(self, var):
        return (
            var.get("valueFrom", {}).get("configMapKeyRef", {}).get("name") == self.name
        )

    def is_used_by_volume(self, volume):
        return volume.get("configMap", {}).get("name") == self.name


@kopf.on.update(*(Secret.REF))
def change_secret_fn(**kwargs):
    Secret(**kwargs).handle()


@kopf.on.update(*(ConfigMap.REF))
def change_cm_fn(**kwargs):
    ConfigMap(**kwargs).handle()
