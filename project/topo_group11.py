#!/usr/bin/env python3
"""
Group 11 - Security of SDN Project
Testbed topology: 4 OpenFlow 1.3 switches, 6 hosts, one redundant route.

Ring: s1 - s2 - s3 - s4 - s1  (any two switches have two disjoint paths)
Hosts: h1@s1, h2@s2, h5@s2, h3@s3, h6@s3, h4@s4
Subnet: 10.1.0.0/24 (single L2 subnet so ONOS host discovery + reactive
forwarding give full host-to-host connectivity; controller itself stays on
the separate Docker network sdn-net = 10.0.0.0/24, ONOS at 10.0.0.10).

Usage:
  sudo python3 topo_group11.py            # build network, verify, drop to CLI
  sudo mn --custom topo_group11.py --topo group11 \
       --controller=remote,ip=10.0.0.10,port=6653 --switch ovs,protocols=OpenFlow13
"""

from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.topo import Topo

CONTROLLER_IP = "10.0.0.10"
CONTROLLER_PORT = 6653

# Hosts: name -> (ip, attached switch)
HOSTS = {
    "h1": ("10.1.0.1/24", "s1"),
    "h2": ("10.1.0.2/24", "s2"),
    "h3": ("10.1.0.3/24", "s3"),
    "h4": ("10.1.0.4/24", "s4"),
    "h5": ("10.1.0.5/24", "s2"),
    "h6": ("10.1.0.6/24", "s3"),
}

# Ring data-plane links (the s1-s4 link plus the s1-s2-s3-s4 chain form the
# redundant route between any two adjacent switches).
RING_LINKS = [("s1", "s2"), ("s2", "s3"), ("s3", "s4"), ("s4", "s1")]


class Group11Topo(Topo):
    "Group 11 project topology."

    def build(self):
        for sw in ("s1", "s2", "s3", "s4"):
            self.addSwitch(sw, protocols="OpenFlow13")
        for host, (ip, sw) in HOSTS.items():
            self.addHost(host, ip=ip)
            self.addLink(host, sw)
        for a, b in RING_LINKS:
            self.addLink(a, b)


topos = {"group11": (lambda: Group11Topo())}


def build_network():
    """Build a Mininet network object with the remote ONOS controller."""
    topo = Group11Topo()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip=CONTROLLER_IP, port=CONTROLLER_PORT
        ),
        switch=OVSSwitch,
    )
    return net


def verify(net):
    info("*** Nodes:\n")
    print(net.nodes)
    info("*** Links:\n")
    print(net.links)
    info("*** Baseline pingall (expect 15/15 received once ONOS fwd is active)\n")
    print(net.pingAll())


if __name__ == "__main__":
    setLogLevel("info")
    net = build_network()
    net.start()
    verify(net)
    CLI(net)
    net.stop()
