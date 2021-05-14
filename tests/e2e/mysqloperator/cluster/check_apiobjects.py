# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License, version 2.0,
# as published by the Free Software Foundation.
#
# This program is also distributed with certain software (including
# but not limited to OpenSSL) that is licensed under separate terms, as
# designated in a particular file or component or in included license
# documentation.  The authors of MySQL hereby grant you an additional
# permission to link the program and your derivative works with the
# separately licensed software that they have included with MySQL.
# This program is distributed in the hope that it will be useful,  but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU General Public License, version 2.0, for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA

import time
from mysqloperator.controller import config
from utils import kutil


def check_pod_labels(test, pod, cluster, role):
    test.assertEqual(pod["metadata"]["labels"]["component"],
                     "mysqld", pod["metadata"]["name"])
    test.assertEqual(pod["metadata"]["labels"]["tier"],
                     "mysql", pod["metadata"]["name"])
    test.assertEqual(pod["metadata"]["labels"]
                     ["mysql.oracle.com/cluster"], cluster, pod["metadata"]["name"])
    test.assertEqual(pod["metadata"]["labels"]
                     ["mysql.oracle.com/cluster-role"], role, pod["metadata"]["name"])


# Check internal sanity of the object
def check_cluster_object(test, icobj, name):
    meta = icobj["metadata"]

    test.assertEqual(icobj["metadata"]["name"], name)

    # check for expected finalizers
    fin = icobj["metadata"]["finalizers"]
    test.assertIn("mysql.oracle.com/cluster", fin)

    # creationTime
    # icobj["status"]["createTime"]
    # TODO

    # child objects

    # server statefulset
    sts = kutil.get_sts(meta["namespace"], meta["name"])
    test.assertTrue(sts)

    # router replicaset
    try:
        rs = kutil.get_rs(meta["namespace"], meta["name"]+"-router")
    except kutil.subprocess.CalledProcessError as e:
        if "(NotFound)" in e.stderr.decode("utf8"):
            rs = None
        else:
            raise
    if icobj["spec"].get("router") and icobj["spec"]["router"].get("instances"):
        test.assertTrue(rs)
    else:
        test.assertFalse(rs)

    # main router service
    svc = kutil.get_svc(meta["namespace"], meta["name"])
    test.assertTrue(svc)

    # direct server service
    svc = kutil.get_svc(meta["namespace"], meta["name"]+"-instances")
    test.assertTrue(svc)


def check_pod_object(test, pod, name):
    test.assertEqual(pod["metadata"]["name"], name)

    # finalizer
    fin = pod["metadata"]["finalizers"]
    test.assertIn("mysql.oracle.com/membership", fin)


def check_cluster_spec_compliant(test, icobj):
    meta = icobj["metadata"]
    spec = icobj["spec"]

    name = meta["name"]

    # server statefulset
    sts = kutil.get_sts(meta["namespace"], meta["name"])
    test.assertTrue(sts)
    test.assertEqual(sts["spec"]["replicas"], spec["instances"])

    # router replicaset
    try:
        rs = kutil.get_rs(meta["namespace"], meta["name"]+"-router")
    except kutil.subprocess.CalledProcessError as e:
        if "(NotFound)" in e.stderr.decode("utf8"):
            rs = None
        else:
            raise
    if spec.get("router") and spec["router"].get("instances"):
        test.assertTrue(rs)
        test.assertEqual(rs["spec"]["replicas"], spec["router"]["instances"])
    else:
        test.assertFalse(rs)

    # check actual pod count
    test.assertEqual(icobj["status"]["cluster"]
                     ["onlineInstances"], spec["instances"])

    pods = kutil.ls_po(meta["namespace"])
    server_pods = [p for p in pods if p["NAME"].startswith(
        name+"-") and "router" not in p["NAME"]]
    test.assertEqual(len(server_pods), spec["instances"])

    router_pods = [p for p in pods if p["NAME"].startswith(name+"-router-")]
    test.assertEqual(len(router_pods), spec.get(
        "router", {}).get("instances", 0))

    # if "image" in spec:
    #     test.assertEqual(icobj["status"]["version"], spec["image"])
    # else:
    #     test.assertEqual(icobj["status"]["version"], config.DEFAULT_SERVER_VERSION_TAG)


def check_pod_spec_compliant(test, icobj, pod):
    # TODO
    # check that the image matches what we want
    status = pod["status"]

    cont = status["containerStatuses"][0]
    # test.assertEqual(cont["image"], "")

    # check that the spec of the pod complies with the cluster spec or
    # hardcoded/expected values
    spec = pod["spec"]

    test.assertEqual(spec["terminationGracePeriodSeconds"], 30)
    test.assertEqual(spec["restartPolicy"], "Always")
    test.assertEqual(spec["subdomain"], icobj["metadata"]["name"]+"-instances")

    def match_spec(field):
        if field in icobj["spec"]:
            test.assertEqual(icobj["spec"][field], spec.get(field),
                             pod["metadata"]["name"]+"/spec."+field)

    # check imagePull stuff
    match_spec("imagePullPolicy")
    match_spec("imagePullSecrets")

    # check securityAccount

    # check securityAccountName

    # check volumes

    # check tolerations


# Check pod status (containers etc)
def check_online_pod_status(test, pod):
    status = pod["status"]

    test.assertEqual(status["phase"], "Running")

    # all conditions true
    test.assertEqual(len(status["conditions"]), 4)
    for cond in status["conditions"]:
        test.assertEqual(cond["status"], "True")

    test.assertEqual(len(status["initContainerStatuses"]), 1)
    icont = status["initContainerStatuses"][0]
    test.assertEqual(icont["name"], "initconf")

    # should be ready and no restarts expected
    test.assertEqual(len(status["containerStatuses"]), 1)
    cont = status["containerStatuses"][0]
    test.assertEqual(cont["name"], "mysql")
    test.assertEqual(cont["ready"], True)
    test.assertEqual(cont["restartCount"], 0)
    test.assertIn("running", cont["state"])

    # no probe failures expected
    # all flags ready
    # check readiness gate


# Check that the output of kubectl get ic matches what it's supposed to be from the rsrc
def check_kubectl_get_ic(test, ns, name, allow_others):
    iclist = kutil.ls_ic(ns)
    if not allow_others:
        test.assertEqual(len(iclist), 1)
    test.assertEqual(list(iclist[0].keys()), [
                     "NAME", "STATUS", "ONLINE", "INSTANCES", "ROUTERS", "AGE"], "expected columns")
    ic = {}
    for tmp in iclist:
        if tmp["NAME"] == name:
            ic = tmp
            break
    else:
        test.assertFalse(True, f"Couldn't find {name} in get ic output")

    icobj = kutil.get_ic(ns, name)
    test.assertTrue(icobj)

    test.assertEqual(ic["NAME"], icobj["metadata"]["name"], str(ic))
    test.assertEqual(ic["STATUS"], icobj["status"]
                     ["cluster"]["status"], str(ic))
    test.assertEqual(ic["ONLINE"], str(
        icobj["status"]["cluster"]["onlineInstances"]), str(ic))
    test.assertEqual(ic["INSTANCES"], str(icobj["spec"]["instances"]), str(ic))
    test.assertEqual(ic["ROUTERS"], str(
        icobj["spec"].get("router", {}).get("instances", "")), str(ic))


def check_kubectl_get_pod(test, ns, name):
    # TODO
    pass


##

def get_cluster_object(test, ns, name):
    icobj = kutil.get_ic(ns, name)
    test.assertNotEqual(icobj, None)
    test.assertEqual(icobj["metadata"]["name"], name)
    test.assertEqual(icobj["metadata"]["namespace"], ns)

    mysql_pods = []
    for i in range(icobj["spec"]["instances"]):
        pod = kutil.get_po(ns, f"{name}-{i}")
        test.assertNotEqual(pod, None)
        test.assertEqual(pod["metadata"]["name"], f"{name}-{i}")
        test.assertEqual(pod["metadata"]["namespace"], ns)
        mysql_pods.append(pod)

    return icobj, mysql_pods


def check_online_cluster(test, icobj, allow_others=False):
    check_kubectl_get_ic(
        test, icobj["metadata"]["namespace"], icobj["metadata"]["name"], allow_others)

    check_cluster_spec_compliant(test, icobj)

    check_cluster_object(test, icobj, icobj["metadata"]["name"])

    return icobj


def check_online_pod(test, icobj, pod, role):
    check_kubectl_get_pod(
        test, icobj["metadata"]["namespace"], pod["metadata"]["name"])

    check_pod_spec_compliant(test, icobj, pod)

    check_pod_object(test, pod, pod["metadata"]["name"])

    # try a couple of times because the labels can take a while to get updated
    i = 5
    while True:
        try:
            check_pod_labels(test, pod, icobj["metadata"]["name"], role)
            break
        except:
            i -= 1
            if i >= 0:
                time.sleep(2)
                pod = kutil.get_po(
                    pod['metadata']['namespace'], pod['metadata']['name'])
            else:
                raise

    # check versions

    return pod


def get_pod_container(pod, container_name):
    for cont in pod["status"]["containerStatuses"]:
        if cont["name"] == container_name:
            return cont
    return None


def check_pod_container(test, pod, container_name, restarts=1, running=True):
    cont = get_pod_container(pod, container_name)
    test.assertTrue(cont, pod["metadata"]["name"]+":"+container_name)
    if restarts is not None:
        test.assertEqual(cont["restartCount"], restarts,
                         pod["metadata"]["name"]+":"+container_name)
    test.assertEqual(bool(cont["state"].get("running")),
                     running, pod["metadata"]["name"]+":"+container_name)
    return cont


def check_router_pod(test, pod, restarts=None):
    check_pod_container(test, pod, "router", restarts=restarts, running=True)

##

# Check that the spec matches what we expect


def check_cluster_spec(test, icobj, instances, routers):
    if instances is not None:
        test.assertEqual(icobj["spec"]["instances"], instances)

    if routers is not None:
        test.assertEqual(icobj["spec"].get(
            "router", {}).get("instances", 0), routers)