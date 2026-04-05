"""
Constant values and default settings for alred.
"""

DEVICE_MAP = {
    "nxos": {
        "ansible_network_os": "cisco.nxos.nxos",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_nxos",
    },
    "ios": {
        "ansible_network_os": "cisco.ios.ios",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_ios",
    },
    "iosxe": {
        "ansible_network_os": "cisco.ios.ios",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_ios",
    },
    "iosxr": {
        "ansible_network_os": "cisco.iosxr.iosxr",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_xr",
    },
    "eos": {
        "ansible_network_os": "arista.eos.eos",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "arista_eos",
    },
    "junos": {
        "ansible_network_os": "junipernetworks.junos.junos",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "juniper_junos",
    },
    "asa": {
        "ansible_network_os": "cisco.asa.asa",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_asa",
    },
    "asav": {
        "ansible_network_os": "cisco.asa.asa",
        "ansible_connection": "network_cli",
        "netmiko_device_type": "cisco_asa",
    },
    "linux": {
        "ansible_connection": "ssh",
        "netmiko_device_type": "linux",
    },
}

DEVICE_TYPE_TO_KIND = {
    "nxos": "cisco_n9kv",
    "ios": "cisco_iosv",
    "iosxe": "cisco_c8000v",
    "iosxr": "cisco_xrd",
    "eos": "ceos",
    "junos": "juniper_vjunosrouter",
    "asa": "cisco_asav",
    "asav": "cisco_asav",
    "linux": "linux",
    "unknown": "linux",
}

NETWORK_DEVICE_TYPES = {"nxos", "ios", "iosxe", "iosxr", "eos", "junos", "asa", "asav"}
PRIVILEGED_EXEC_DEVICE_TYPES = {"asa", "asav"}

DEFAULT_POLICY = {
    "include_device_types": [],
    "include_hostname_contains": [],
    "exclude_device_types": [],
    "exclude_hostname_contains": [],
    "collect_running_config_for": ["nxos", "ios", "iosxe", "iosxr", "eos", "junos", "asa", "asav"],
}

DEFAULT_MAPPINGS = {
    "node_name_map": {},
    "interface_name_map": {},
    "exclude_interfaces": [
        "mgmt0",
        "management",
        "loopback0",
        "lo",
        "vlan1",
        "Port-channel",
        "port-channel",
    ],
}

DEFAULT_ROLES = {
    "role_detection": {
        "border-gateway": {
            "priority": 0,
            "contains": ["bgw"],
        },
        "super-spine": {
            "priority": 1,
            "contains": ["ss"],
        },
        "spine": {
            "priority": 2,
            "contains": ["sp"],
        },
        "underlay-route-reflector": {
            "priority": 2,
            "contains": ["sp"],
        },
        "leaf": {
            "priority": 3,
            "contains": ["lf"],
        },
        "network-functions": {
            "priority": 4,
            "contains": ["bgrt"],
        },
        "server": {
            "priority": 5,
            "contains": ["server", "host", "srv", "worker", "control-plane"],
        },
    }
}

DEFAULT_DESCRIPTION_RULES = {
    "description_rules": [
        {
            "name": "to_hostname_interface",
            "regex": r"TO[_ -]?(?P<remote_host>[A-Za-z0-9._-]+)[_ -]+(?P<remote_if>(?:Eth|eth|Ethernet|Gi|gi|GigabitEthernet|Te|te|TenGigabitEthernet|Po|po|Port-channel|port-channel|ens|enp|eno|bond|br)\S*)",
        },
        {
            "name": "hostname_interface_space",
            "regex": r"(?P<remote_host>[A-Za-z0-9._-]+)[ _:-]+(?P<remote_if>(?:Eth|eth|Ethernet|Gi|gi|GigabitEthernet|Te|te|TenGigabitEthernet|Po|po|Port-channel|port-channel|ens|enp|eno|bond|br)\S*)",
        },
        {
            "name": "hostname_only",
            "regex": r"^(?P<remote_host>[A-Za-z0-9._-]+)$",
        },
    ]
}

CONFIDENCE_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}

LLDP_COMMAND_MAP = {
    "nxos": "show lldp neighbors detail",
    "ios": "show lldp neighbors detail",
    "iosxe": "show lldp neighbors detail",
    "iosxr": "show lldp neighbors detail",
    "eos": "show lldp neighbors detail",
    "junos": "show lldp neighbors",
    "asa": "show lldp neighbors detail",
    "asav": "show lldp neighbors detail",
    "linux": "lldpcli show neighbors",
}

SHOW_LOGGING_COMMAND_MAP = {
    "nxos": "show logging",
}

DEFAULT_LOGGING_THRESHOLD_MAP = {
    "nxos": 4,
}

RUNNING_CONFIG_COMMAND_MAP = {
    "nxos": "show running-config",
    "ios": "show running-config",
    "iosxe": "show running-config",
    "iosxr": "show running-config",
    "eos": "show running-config",
    "junos": "show configuration | display set",
    "asa": "show running-config",
    "asav": "show running-config",
}

RUNNING_CONFIG_DIFF_COMMAND_MAP = {
    "nxos": "show running-config diff",
}

RUNNING_CONFIG_DIFF_EXCLUDE_PREFIXES_MAP = {
    "nxos": ["!"],
}

SAVE_CONFIG_COMMAND_MAP = {
    "nxos": "copy running-config startup-config",
    "ios": "write memory",
    "iosxe": "write memory",
    "iosxr": "commit",
    "eos": "write memory",
    "junos": "commit",
    "asa": "write memory",
    "asav": "write memory",
}

SAVE_CONFIG_SUCCESS_MARKER_MAP = {
    "nxos": "Copy complete.",
}

CONNECT_CHECK_COMMAND_MAP = {
    "nxos": "show clock",
    "ios": "show clock",
    "iosxe": "show clock",
    "iosxr": "show clock",
    "eos": "show clock",
    "junos": "show system uptime",
    "asa": "show clock",
    "asav": "show clock",
    "linux": "date",
}

PUSH_CONFIG_EXCLUDE_LINE_PREFIXES_MAP = {
    "nxos": ["!", "version", "copp"],
}

DEFAULT_LOG_ROTATION = 20
DEFAULT_HOSTS_PATH = "hosts.yaml"
DEFAULT_DESCRIPTION_RULES_PATH = "description_rules.yaml"
DEFAULT_ROLES_PATH = "roles.yaml"
DEFAULT_SHOW_COMMANDS_PATH = "show_commands.txt"
DEFAULT_SAMPLES_DIR = "samples"
DEFAULT_LINKS_CONFIRMED_FILENAME = "links_confirmed.csv"
DEFAULT_LINKS_CANDIDATES_FILENAME = "links_candidates.csv"
DEFAULT_TOPOLOGY_CLAB_FILENAME = "topology.clab.yaml"
DEFAULT_TOPOLOGY_MERMAID_FILENAME = "topology-graph.md"
DEFAULT_TOPOLOGY_GRAPHVIZ_FILENAME = "topology-graph.dot"
DEFAULT_TOPOLOGY_DRAWIO_FILENAME = "topology-graph.drawio"
DEFAULT_TOPOLOGY_DRAWIO_ALL_FILENAME = "topology-graph-all.drawio"
DEFAULT_TOPOLOGY_NO_CANDIDATE_MERMAID_FILENAME = "topology_no_candidates.md"
DEFAULT_VNI_MAP_CSV_FILENAME = "vni_gateway_map.csv"
DEFAULT_VNI_MAP_MD_FILENAME = "vni_gateway_map.md"
DRAWIO_HOST = "app.diagrams.net"
DRAWIO_VERSION = "24.7.17"
DRAWIO_MODEL_ATTRIBUTES = {
    "dx": "1600",
    "dy": "1200",
    "grid": "1",
    "gridSize": "10",
    "guides": "1",
    "tooltips": "1",
    "connect": "1",
    "arrows": "1",
    "fold": "1",
    "page": "1",
    "pageScale": "1",
    "pageWidth": "1920",
    "pageHeight": "1080",
    "math": "0",
    "shadow": "0",
}
DRAWIO_LAYOUT = {
    "origin_x": 40,
    "origin_y": 80,
    "node_width": 220,
    "node_height": 72,
    "node_gap_x": 60,
    "node_gap_y": 40,
    "container_padding": 20,
    "container_header": 36,
    "container_gap": 80,
    "nic_top_gap": 12,
    "nic_box_width": 140,
    "nic_box_height": 22,
    "nic_box_gap": 8,
}
DRAWIO_STYLE_NODE = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "strokeColor=#1f2937;fillColor=#f9fafb;fontColor=#111827;"
)
DRAWIO_STYLE_DEVICE_CONTAINER = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "strokeColor=#1f2937;fillColor=#f9fafb;fontColor=#111827;"
)
DRAWIO_STYLE_DEVICE_LABEL = (
    "rounded=0;whiteSpace=wrap;html=1;"
    "strokeColor=none;fillColor=none;fontColor=#111827;"
    "align=center;verticalAlign=middle;"
)
DRAWIO_STYLE_CONTAINER = (
    "swimlane;rounded=1;whiteSpace=wrap;html=1;"
    "strokeColor=#94a3b8;fillColor=#eef2ff;fontColor=#0f172a;"
)
DRAWIO_STYLE_LEAF_CONTAINER = (
    "swimlane;rounded=1;whiteSpace=wrap;html=1;"
    "strokeColor=#64748b;fillColor=#dbeafe;fontColor=#0f172a;"
)
DRAWIO_STYLE_NIC = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "strokeColor=#94a3b8;fillColor=#ffffff;fontColor=#334155;"
    "fontSize=10;"
)
DRAWIO_STYLE_EDGE = "endArrow=none;html=1;rounded=0;strokeColor=#475569;jumpStyle=arc;jumpSize=6;"
DRAWIO_STYLE_EDGE_DASHED_SUFFIX = "dashed=1;strokeColor=#94a3b8;"
DEFAULT_CONNECT_CHECK_TIMEOUT = 3.0
DEFAULT_CLAB_TOPOLOGY_NAME = "network01"
DEFAULT_CLAB_SET_GENERATE_CLAB_AUTO_FILES = {
    "linux_csv": "clab_linux_server.csv",
    "kind_cluster_csv": "clab_kind_cluster.csv",
    "clab_merge": "clab_merge.yaml",
    "clab_lab_profile": "clab_lab_profile.yaml",
}
DEFAULT_CLAB_SET_CMDS = [
    {
        "name": "collect-clab",
        "command": "collect",
        "args": {
            "command": "collect-clab",
            "hosts": None,
            "policy": None,
            "roles": None,
            "username": None,
            "password": None,
            "enable_secret": None,
            "transport": "auto",
            "target_hosts": None,
            "output": "raw",
            "before_show_run_dir": None,
            "workers": 5,
            "show_read_timeout": 120,
            "show_only": False,
            "show_run_diff": False,
            "show_run_diff_comands": False,
            "show_commands_file": None,
            "show_hosts": None,
            "log_file": "logs/collect-clab.log",
        },
    },
    {
        "name": "clab-transform-config",
        "command": "clab-transform-config",
        "args": {
            "command": "clab-transform-config",
            "hosts": None,
            "clab_env": None,
            "input": "raw",
            "output_hosts": "hosts.lab.yaml",
            "output_dir": "raw/labconfig",
            "log_file": "logs/clab-transform-config.log",
        },
    },
    {
        "name": "normalize-links",
        "command": "normalize-links",
        "args": {
            "command": "normalize-links",
            "input": "raw",
            "output_confirmed": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "output_candidates": f"output/{DEFAULT_LINKS_CANDIDATES_FILENAME}",
            "hosts": None,
            "mappings": None,
            "description_rules": None,
            "log_file": "logs/normalize-links.log",
        },
    },
    {
        "name": "generate-clab",
        "command": "generate-clab",
        "args": {
            "command": "generate-clab",
            "input": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "hosts": None,
            "mappings": None,
            "roles": None,
            "min_confidence": "low",
            "include_nodes": True,
            "group_by_role": True,
            "linux_csv": None,
            "kind_cluster_csv": None,
            "clab_merge": None,
            "clab_lab_profile": None,
            "name": DEFAULT_CLAB_TOPOLOGY_NAME,
            "output": f"output/{DEFAULT_TOPOLOGY_CLAB_FILENAME}",
            "log_file": "logs/generate-clab.log",
        },
    },
    {
        "name": "generate-mermaid",
        "command": "generate-mermaid",
        "args": {
            "command": "generate-mermaid",
            "input": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "input_candidates": f"output/{DEFAULT_LINKS_CANDIDATES_FILENAME}",
            "hosts": None,
            "mappings": None,
            "roles": "roles.yaml",
            "min_confidence": "low",
            "direction": "LR",
            "group_by_role": True,
            "add_comments": False,
            "underlay": False,
            "underlay_config": None,
            "underlay_raw": "raw",
            "title": "Network Topology",
            "output": f"output/{DEFAULT_TOPOLOGY_MERMAID_FILENAME}",
            "log_file": "logs/generate-mermaid.log",
        },
    },
    {
        "name": "generate-mermaid-no-candidates",
        "command": "generate-mermaid",
        "args": {
            "command": "generate-mermaid",
            "input": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "input_candidates": None,
            "hosts": None,
            "mappings": None,
            "roles": "roles.yaml",
            "min_confidence": "low",
            "direction": "LR",
            "group_by_role": True,
            "add_comments": False,
            "underlay": False,
            "underlay_config": None,
            "underlay_raw": "raw",
            "title": "Network Topology (No Candidate)",
            "output": f"output/{DEFAULT_TOPOLOGY_NO_CANDIDATE_MERMAID_FILENAME}",
            "log_file": "logs/generate-mermaid.log",
        },
    },
    {
        "name": "generate-mermaid-underlay",
        "command": "generate-mermaid",
        "args": {
            "command": "generate-mermaid",
            "input": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "input_candidates": None,
            "hosts": None,
            "mappings": None,
            "roles": "roles.yaml",
            "min_confidence": "low",
            "direction": "LR",
            "group_by_role": True,
            "add_comments": False,
            "underlay": True,
            "underlay_config": "underlay_render.yaml",
            "underlay_raw": "raw",
            "title": "Network Topology",
            "output": f"output/{DEFAULT_TOPOLOGY_MERMAID_FILENAME}",
            "log_file": "logs/generate-mermaid-underlay.log",
        },
    },
    {
        "name": "generate-drawio-all-graph",
        "command": "generate-drawio",
        "args": {
            "command": "generate-drawio",
            "input": f"output/{DEFAULT_LINKS_CONFIRMED_FILENAME}",
            "input_candidates": f"output/{DEFAULT_LINKS_CANDIDATES_FILENAME}",
            "hosts": None,
            "mappings": None,
            "roles": "roles.yaml",
            "min_confidence": "low",
            "direction": "TD",
            "group_by_role": True,
            "add_comments": False,
            "all_graph": True,
            "underlay": False,
            "underlay_config": "underlay_render.yaml",
            "underlay_raw": "raw",
            "title": "Network Topology",
            "output": f"output/{DEFAULT_TOPOLOGY_DRAWIO_ALL_FILENAME}",
            "log_file": "logs/generate-drawio-all-graph.log",
        },
    },
    {
        "name": "generate-vni-map",
        "command": "generate-vni-map",
        "args": {
            "command": "generate-vni-map",
            "input": "raw",
            "output_csv": f"output/{DEFAULT_VNI_MAP_CSV_FILENAME}",
            "output_md": f"output/{DEFAULT_VNI_MAP_MD_FILENAME}",
            "title": "VNI / VRF / Gateway Map",
            "include_vlan_name": True,
            "log_file": "logs/generate-vni-map.log",
        },
    },
]

DEFAULT_LINUX_KIND_IMAGE = "ghcr.io/hellt/network-multitool:latest"
DEFAULT_LINUX_NODE_BIND = ".alred/linux:/scripts:ro"
DEFAULT_LINUX_NODE_EXEC = "sh -lc '/scripts/init-bond-singlevlan-route.sh'"

DEFAULT_KIND_CLUSTER_KIND = "k8s-kind"
DEFAULT_KIND_CLUSTER_IMAGE = "kindest/node:v1.34.3"
DEFAULT_KIND_CLUSTER_STARTUP_CONFIG_TEMPLATE = ".alred/{cluster}/{cluster}.kind.yaml"
DEFAULT_KIND_CLUSTER_CONFIG_BASE_DIR = ".alred"
DEFAULT_KIND_CLUSTER_CONFIG_FILENAME_TEMPLATE = "{cluster}.kind.yaml"
DEFAULT_KIND_CLUSTER_CONFIG_MOUNT_SUBDIR = "linux"
DEFAULT_KIND_CLUSTER_CONFIG_CONTAINER_MOUNT_PATH = "/scripts"
DEFAULT_KIND_CLUSTER_NODE_SCRIPT_FILENAME = "init-bond-singlevlan-route.sh"
DEFAULT_KIND_CLUSTER_NODE_SCRIPT_CONTENT = """#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# init-bond-singlevlan-route.sh (containerlab/kind friendly)
# - Create LACP bond0 (802.3ad) on eth1+eth2
# - Create a single VLAN sub-interface bond0.<VLAN_ID>
# - Assign IPv4/IPv6 address
# - (Optional) Set default routes (disabled by default to avoid breaking kind/k8s)
# - (Optional) Add static routes for node routing (NEW)
# - Set MTU on bond/VLAN/slaves (default 9000)
#
# Required env:
#   VLAN_ID   : e.g. 101
#   IP_CIDR   : e.g. 192.168.101.11/24
#
# Optional env:
#   DEF_GW    : e.g. 192.168.101.1        (only used if SET_DEFAULT_ROUTE=true)
#   IPV6_CIDR : e.g. 2001:db8:101::11/64
#   DEF_GW6   : e.g. 2001:db8:101::1      (only used if SET_DEFAULT_ROUTE=true)
#   MTU       : e.g. 9000 (default 9000)
#   SET_DEFAULT_ROUTE : "true"|"false" (default false)
#
#   (NEW) ROUTES4 : newline-separated static routes to add (IPv4)
#     Examples:
#       ROUTES4=$'10.10.0.0/16 via 192.168.101.1\\n172.16.0.0/12 dev bond0.101'
#       ROUTES4=$'10.10.0.0/16 via 192.168.101.1 metric 50'
#
#   (NEW) ROUTES6 : newline-separated static routes to add (IPv6)
#     Examples:
#       ROUTES6=$'2001:db8:200::/64 via 2001:db8:101::1\\n2001:db8:300::/64 dev bond0.101'
#
#   BOND_MODE : e.g. 802.3ad (default 802.3ad)
#   MIIMON    : e.g. 100 (default 100)
#   LACP_RATE : e.g. fast|slow (default fast)
#   XMIT_HASH_POLICY : e.g. layer3+4 (default layer3+4)
# ============================================================

# ---- required vars ----
: "${VLAN_ID:?VLAN_ID is required (e.g. 101)}"
: "${IP_CIDR:?IP_CIDR is required (e.g. 192.168.101.11/24)}"

# ---- optional vars ----
DEF_GW="${DEF_GW:-}"
IPV6_CIDR="${IPV6_CIDR:-}"
DEF_GW6="${DEF_GW6:-}"

MTU="${MTU:-9000}"
SET_DEFAULT_ROUTE="${SET_DEFAULT_ROUTE:-false}"

# NEW: static routes
ROUTES4="${ROUTES4:-}"
ROUTES6="${ROUTES6:-}"

BOND_MODE="${BOND_MODE:-802.3ad}"
MIIMON="${MIIMON:-100}"
LACP_RATE="${LACP_RATE:-fast}"
XMIT_HASH_POLICY="${XMIT_HASH_POLICY:-layer3+4}"

VIF="bond0.${VLAN_ID}"

log() { echo "[$(date +'%F %T')] $*"; }

# ------------------------------------------------------------
# Best-effort: try to load required kernel modules
# ------------------------------------------------------------
try_modprobe() {
  local m="$1"
  if lsmod | awk '{print $1}' | grep -qx "$m"; then
    log "[OK] module already loaded: $m"
    return 0
  fi

  if command -v modprobe >/dev/null 2>&1; then
    if modprobe "$m" >/dev/null 2>&1; then
      log "[INFO] loaded module: $m"
      return 0
    else
      log "[WARN] modprobe $m failed (likely not privileged / no /lib/modules mount)."
      return 1
    fi
  else
    log "[WARN] modprobe not found in container."
    return 1
  fi
}

try_modprobe bonding || true
try_modprobe 8021q   || true

# ------------------------------------------------------------
# Helpers: add routes (NEW)
# ------------------------------------------------------------
add_routes_v4() {
  local routes="$1"
  [[ -z "$routes" ]] && return 0

  log "[INFO] adding IPv4 static routes (ROUTES4)"
  # Each non-empty, non-comment line is appended to: ip route replace <line>
  while IFS= read -r line; do
    # trim leading/trailing spaces (bash-safe)
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^# ]] && continue

    log "  [ROUTE4] ip route replace $line"
    ip route replace $line
  done <<< "$routes"
}

add_routes_v6() {
  local routes="$1"
  [[ -z "$routes" ]] && return 0

  log "[INFO] adding IPv6 static routes (ROUTES6)"
  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    [[ "$line" =~ ^# ]] && continue

    log "  [ROUTE6] ip -6 route replace $line"
    ip -6 route replace $line
  done <<< "$routes"
}

# ------------------------------------------------------------
# Sanity checks
# ------------------------------------------------------------
if ! ip link show eth1 >/dev/null 2>&1 || ! ip link show eth2 >/dev/null 2>&1; then
  log "[ERROR] eth1/eth2 not found. Check containerlab links."
  ip link show || true
  exit 1
fi

# Check if bonding is available by attempting to create a test bond.
if ! ip link add __bond_test type bond >/dev/null 2>&1; then
  log "[ERROR] Cannot create bonding interface. Host kernel module 'bonding' is not available/loaded."
  log "[ERROR] Fix on host: sudo modprobe bonding && sudo modprobe 8021q"
  exit 1
else
  ip link del __bond_test >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------
# Create bond0 (LACP or chosen mode)
# ------------------------------------------------------------
if ip link show bond0 >/dev/null 2>&1; then
  log "[INFO] bond0 already exists; reconfiguring slaves/state."
else
  log "[INFO] creating bond0 (mode=${BOND_MODE})"
  if [[ "${BOND_MODE}" == "802.3ad" ]]; then
    ip link add bond0 type bond \
      mode 802.3ad \
      miimon "${MIIMON}" \
      lacp_rate "${LACP_RATE}" \
      xmit_hash_policy "${XMIT_HASH_POLICY}"
  else
    ip link add bond0 type bond mode "${BOND_MODE}" miimon "${MIIMON}"
  fi
fi

# Attach slaves safely
ip link set eth1 down || true
ip link set eth2 down || true
ip link set eth1 master bond0 || true
ip link set eth2 master bond0 || true

# MTU: set on slaves and bond
log "[INFO] setting MTU=${MTU} on eth1/eth2/bond0"
ip link set eth1 mtu "${MTU}" || true
ip link set eth2 mtu "${MTU}" || true
ip link set bond0 mtu "${MTU}" || true

ip link set bond0 up
ip link set eth1 up
ip link set eth2 up

# ------------------------------------------------------------
# Create single VLAN sub-interface on bond0
# ------------------------------------------------------------
if ip link show "${VIF}" >/dev/null 2>&1; then
  log "[INFO] ${VIF} already exists"
else
  log "[INFO] creating VLAN sub-interface ${VIF} (id ${VLAN_ID})"
  ip link add link bond0 name "${VIF}" type vlan id "${VLAN_ID}"
fi

log "[INFO] setting MTU=${MTU} on ${VIF}"
ip link set "${VIF}" mtu "${MTU}" || true
ip link set "${VIF}" up

# ------------------------------------------------------------
# IPv4 address + (optional) default route
# ------------------------------------------------------------
log "[INFO] configuring IPv4 on ${VIF}: ${IP_CIDR}"
ip addr replace "${IP_CIDR}" dev "${VIF}"

if [[ "${SET_DEFAULT_ROUTE}" == "true" ]]; then
  if [[ -z "${DEF_GW}" ]]; then
    log "[ERROR] SET_DEFAULT_ROUTE=true but DEF_GW is not set."
    exit 1
  fi
  log "[WARN] replacing IPv4 default route via ${DEF_GW} on ${VIF}"
  ip route replace default via "${DEF_GW}" dev "${VIF}"
else
  log "[INFO] SET_DEFAULT_ROUTE=false; keeping existing IPv4 default route (likely via eth0)."
fi

# NEW: IPv4 static routes
add_routes_v4 "${ROUTES4}"

# ------------------------------------------------------------
# IPv6 address + (optional) default route
# ------------------------------------------------------------
if [[ -n "${IPV6_CIDR}" ]]; then
  log "[INFO] enabling IPv6 sysctls (best-effort)"
  sysctl -w net.ipv6.conf.all.disable_ipv6=0 >/dev/null 2>&1 || true
  sysctl -w net.ipv6.conf.default.disable_ipv6=0 >/dev/null 2>&1 || true
  sysctl -w "net.ipv6.conf.${VIF}.disable_ipv6=0" >/dev/null 2>&1 || true

  log "[INFO] configuring IPv6 on ${VIF}: ${IPV6_CIDR}"
  ip -6 addr replace "${IPV6_CIDR}" dev "${VIF}"

  if [[ "${SET_DEFAULT_ROUTE}" == "true" ]]; then
    if [[ -z "${DEF_GW6}" ]]; then
      log "[ERROR] SET_DEFAULT_ROUTE=true but DEF_GW6 is not set (for IPv6 default route)."
      exit 1
    fi
    log "[WARN] replacing IPv6 default route via ${DEF_GW6} on ${VIF}"
    ip -6 route replace default via "${DEF_GW6}" dev "${VIF}"
  else
    log "[INFO] SET_DEFAULT_ROUTE=false; keeping existing IPv6 default route."
  fi

  # NEW: IPv6 static routes
  add_routes_v6 "${ROUTES6}"
else
  # IPv6_CIDR empty with ROUTES6 still allowed (best-effort)
  if [[ -n "${ROUTES6}" ]]; then
    log "[WARN] ROUTES6 is set but IPV6_CIDR is empty; adding IPv6 routes anyway (best-effort)."
    add_routes_v6 "${ROUTES6}"
  fi
fi

# ------------------------------------------------------------
# Summary
# ------------------------------------------------------------
log "[INFO] done. Current link/address/route summary:"
ip -d link show bond0 || true
ip -d link show "${VIF}" || true
ip addr show dev "${VIF}" || true
ip route || true
ip -6 route || true
"""
DEFAULT_KIND_NODE_BIND = "k8s_kind/node:/scripts:ro"
DEFAULT_KIND_NODE_INIT_SCRIPT = "/scripts/init-bond-singlevlan-route.sh"

DEFAULT_CISCO_N9KV_KIND_NAME = "cisco_n9kv"
DEFAULT_CISCO_N9KV_KIND_IMAGE = "vrnetlab/cisco_n9kv:10.5.4.M.lite"
DEFAULT_CISCO_N9KV_STARTUP_CONFIG_TEMPLATE = "{raw_dir}/labconfig/__clabNodeName___run.txt"
DEFAULT_CISCO_N9KV_KIND_ENV = {
    "QEMU_MEMORY": 6144,
    "QEMU_SMP": 4,
    "CLAB_MGMT_PASSTHROUGH": "true",
}
