#!/bin/bash

service openvswitch-switch start

ovs-vsctl show

exec "$@"
