#!/bin/bash
# Group 11 lab container entrypoint: datapath modules, OVS daemon, sshd.
set -e

mkdir -p /run/sshd /var/run/sshd

# Load datapath modules against the host kernel metadata (mounted read-only).
if [ -d "/lib/modules/$(uname -r)" ]; then
    for m in openvswitch bridge sch_netem; do
        modprobe "$m" 2>/dev/null || true
    done
fi

# Start Open vSwitch (ovsdb-server + ovs-vswitchd).
if ! service openvswitch-switch start >/dev/null 2>&1; then
    /usr/share/openvswitch/scripts/ovs-ctl --system-id=random start >/dev/null 2>&1 || true
fi
ovs-vsctl --version 2>/dev/null | head -1 || true

# SSH daemon on port 2222 (login mininet/mininet).
/usr/sbin/sshd

echo "sdn-lab ready: OVS up, sshd on 2222 (mininet/mininet), scripts at /home/mininet/group11_sdn_mistral_project"
exec "$@"
