# =============================================================================
# Group 11 - SDN incident explanation with Mistral 7B - lab image
# Project: Explaining Network Incidents in SDN Through Log Analysis Using Mistral 7B
# Team: Eris Mustafa, Shrikant Nimkar - Security of SDN, Universite du Luxembourg
#
# Same base and toolchain as the project reference image: ubuntu:20.04 with
# Mininet 2.3.0 built from source, Open vSwitch, docker CLI (for Karaf log
# capture through the mounted Docker socket), iperf, and SSH on port 2222
# (login mininet/mininet) for interactive use, as in the course labs.
#
# The container runs privileged and on the host kernel: the host must provide
# the Open vSwitch kernel datapath (any standard Ubuntu/Debian kernel does;
# only a stock WSL2 kernel does not).
# =============================================================================

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

# ---- system packages ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl wget ca-certificates \
        openssh-server sudo \
        iproute2 net-tools ethtool iputils-ping \
        tcpdump iperf iperf3 \
        openvswitch-switch openvswitch-common \
        python3 python3-pip python3-requests python3-yaml \
        docker.io \
        dnsutils less vim \
    && rm -rf /var/lib/apt/lists/*

# ---- Mininet 2.3.0 from source (no controllers; ONOS runs in its own container)
RUN git clone --depth 1 -b 2.3.0 https://github.com/mininet/mininet.git /tmp/mininet \
    && cd /tmp/mininet \
    && ./util/install.sh -n \
    && rm -rf /tmp/mininet

# ---- lab user (course-lab workflow: ssh -p 2222 mininet@localhost) -----------
RUN useradd -m -s /bin/bash mininet \
    && echo 'mininet:mininet' | chpasswd \
    && usermod -aG sudo mininet \
    && echo 'mininet ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/mininet \
    && chmod 440 /etc/sudoers.d/mininet \
    && sed -i 's/^#Port 22/Port 2222/' /etc/ssh/sshd_config \
    && mkdir -p /run/sshd /var/run/sshd

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /home/mininet/group11_sdn_mistral_project
EXPOSE 2222

ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
