#!/bin/bash

set -e

echo "Configuring RHLC operator..."
echo ""

echo "Step 1: Installing operator..."
oc apply -f 01-namespace.yaml
oc apply -f 02-operatorgroup.yaml
oc apply -f 03-subscription.yaml

echo "Waiting for operator (this takes 2-5 minutes)..."
until oc get csv -n kuadrant-system 2>/dev/null | grep -q Succeeded; do
    echo -n "."
    sleep 5
done
echo " ✓ Operator ready"
echo ""

echo "Step 2: Creating Kuadrant..."
oc apply -f 04-kuadrant.yaml

echo "Waiting for Kuadrant (this takes 3-10 minutes)..."
oc wait Kuadrant -n kuadrant-system kuadrant --for=condition=Ready --timeout=10m
echo "✓ Kuadrant ready"
echo ""

echo "Step 3: Adding certificate annotation..."
oc annotate svc/authorino-authorino-authorization \
  service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert \
  -n kuadrant-system

echo "Waiting for certificate..."
sleep 5
until oc get secret authorino-server-cert -n kuadrant-system 2>/dev/null; do
    echo -n "."
    sleep 2
done
echo " ✓ Certificate ready"
echo ""

echo "Step 4: Enabling SSL..."
oc apply -f 05-authorino-ssl.yaml

echo "Waiting for Authorino pods..."
oc wait --for=condition=ready pod -l authorino-resource=authorino -n kuadrant-system --timeout=150s
echo "✓ Authorino ready"
echo ""

echo "✓ Complete!"
echo "If OpenShift AI was installed before installing"
echo "Connectivity Link and Kuadrant, restart the controllers:"
echo "  oc delete pod -n redhat-ods-applications -l app=odh-model-controller"
echo "  oc delete pod -n redhat-ods-applications -l control-plane=kserve-controller-manager"
