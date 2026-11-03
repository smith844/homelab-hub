/** Pure network-wide discovery filtering, hierarchy and summary helpers. */
export const HOST_MATCH_FILTERS = [
  { value: 'all', label: 'All hosts' },
  { value: 'matched', label: 'Matched' },
  { value: 'plausible', label: 'Plausible / review' },
  { value: 'shared', label: 'Shared endpoint' },
  { value: 'ambiguous', label: 'Ambiguous' },
  { value: 'unmatched', label: 'Unmatched' },
  { value: 'unverified', label: 'Unverified / incomplete' },
];

export const SERVICE_MATCH_FILTERS = [
  { value: 'all', label: 'All services' },
  { value: 'matched', label: 'Matched' },
  { value: 'plausible', label: 'Plausible / review' },
  { value: 'ambiguous', label: 'Ambiguous' },
  { value: 'unmatched', label: 'Unmatched' },
  { value: 'unverified', label: 'Unverified / incomplete' },
];

export const SOURCE_FILTERS = [
  { value: 'all', label: 'All sources' },
  { value: 'nmap', label: 'Nmap only' },
  { value: 'both', label: 'Nmap + UniFi' },
  { value: 'unifi', label: 'Any UniFi evidence' },
];

export const UNIFI_STATE_FILTERS = [
  { value: 'all', label: 'All UniFi states' },
  { value: 'online', label: 'Online / current' },
  { value: 'offline', label: 'Offline / historical' },
  { value: 'unknown', label: 'Unknown state' },
];

export const DEVICE_TYPE_FILTERS = [
  { value: 'all', label: 'All device types' },
  { value: 'physical', label: 'Physical / network devices' },
  { value: 'runtime', label: 'VMs / runtimes' },
  { value: 'application', label: 'Applications / services' },
  { value: 'unknown', label: 'Unknown' },
];

export const TERMINAL_STATUSES = ['completed', 'partial', 'failed'];

export function scanIsTerminal(status) {
  return TERMINAL_STATUSES.includes(status);
}

export function candidateGroups(row) {
  const candidates = row?.candidates || [];
  const serviceCandidates = row?.service_candidates || [];
  const physical = candidates.filter(candidate =>
    candidate.type === 'hardware' || candidate.type === 'misc');
  const runtimes = candidates.filter(candidate => candidate.type === 'vms');
  const applications = candidates.filter(candidate => candidate.type === 'apps');
  const services = [...serviceCandidates];
  for (const candidate of applications) {
    if (!services.some(item => item.type === candidate.type && item.id === candidate.id)) {
      services.push(candidate);
    }
  }
  return {physical, runtimes, applications, services};
}

export function primaryIdentity(row) {
  const groups = candidateGroups(row);
  return groups.physical[0] || groups.runtimes[0] || groups.services[0]
    || groups.applications[0] || null;
}

export function deviceIdentityCount(row) {
  const groups = candidateGroups(row);
  return groups.physical.length + groups.runtimes.length;
}

export function serviceIdentityCount(row) {
  return candidateGroups(row).services.length;
}

export function hostSourceCategory(row) {
  const sources = row?.sources || ['nmap'];
  if (row?.unifi_only) return 'unifi';
  if (sources.includes('unifi')) return 'both';
  return 'nmap';
}

export function unifiState(row) {
  if (row?.online === true) return 'online';
  if (row?.online === false) return 'offline';
  const matches = row?.unifi_matches || [];
  if (matches.some(item => item.online === true)) return 'online';
  if (matches.some(item => item.online === false)) return 'offline';
  return 'unknown';
}

export function matchesDeviceType(row, type) {
  if (!type || type === 'all') return true;
  const groups = candidateGroups(row);
  const deviceType = String(row?.device_type || '');
  if (type === 'physical') {
    return groups.physical.length > 0 ||
      /gateway|switch|access_point|network_device|wired|wireless|vpn|teleport|client/.test(deviceType);
  }
  if (type === 'runtime') return groups.runtimes.length > 0;
  if (type === 'application') return groups.services.length > 0 || groups.applications.length > 0;
  if (type === 'unknown') {
    return !groups.physical.length && !groups.runtimes.length &&
      !groups.services.length && !groups.applications.length && !deviceType;
  }
  return true;
}

export function deviceTypeCategory(row) {
  const groups = candidateGroups(row);
  if (groups.physical.length) return 'physical';
  if (groups.runtimes.length) return 'runtime';
  if (groups.services.length || groups.applications.length) return 'application';
  if (String(row?.device_type || '').match(/gateway|switch|access_point|network_device/)) return 'physical';
  if (String(row?.device_type || '').match(/wired|wireless|vpn|teleport|client/)) return 'physical';
  return 'unknown';
}

export function networkLabel(row) {
  const network = row?.network;
  if (!network) return '';
  return network.vlan_id !== null && network.vlan_id !== undefined
    ? `${network.name || 'Network'} · VLAN ${network.vlan_id}`
    : network.name || '';
}

export function networksFromResult(result) {
  const names = new Set();
  for (const row of [...(result?.hosts || []), ...(result?.unifi_only || [])]) {
    if (row?.network?.name) names.add(row.network.name);
  }
  return [...names].sort((a, b) => a.localeCompare(b));
}

function _candidateText(row) {
  const candidates = [...(row.candidates || []), ...(row.service_candidates || [])];
  return candidates.map(candidate => [
    candidate.name,
    candidate.category,
    ...(candidate.evidence || []),
  ].join(' ')).join(' ');
}

function _matchesText(row, query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  const unifi = (row.unifi_matches || []).map(item => [
    item.name, item.hostname, item.mac, item.ip, item.network?.name, item.device_type,
  ].join(' ')).join(' ');
  return [
    row.ip, row.hostname, row.mac, row.vendor, row.os, row.port,
    row.service_name, row.service_version, row.classification,
    ...(row.evidence || []), _candidateText(row), unifi,
  ].filter(value => value !== null && value !== undefined)
    .join(' ').toLowerCase().includes(needle);
}

function _matchesNetwork(row, network) {
  if (!network) return true;
  return row?.network?.name === network;
}

function _matchesState(row, state) {
  if (!state || state === 'all') return true;
  return unifiState(row) === state;
}

export function filterHostRows(rows = [], filter = 'all', query = '', options = {}) {
  const {source = 'all', network = '', state = 'all', type = 'all'} = options;
  return (rows || []).filter(row => {
    if (filter !== 'all' && row.classification !== filter) return false;
    const category = hostSourceCategory(row);
    if (source === 'nmap' && category !== 'nmap') return false;
    if (source === 'both' && category !== 'both') return false;
    if (source === 'unifi' && !(row.sources || []).includes('unifi')) return false;
    if (!_matchesNetwork(row, network) || !_matchesState(row, state)) return false;
    if (!matchesDeviceType(row, type)) return false;
    return _matchesText(row, query);
  });
}

export function filterServiceRows(rows = [], filter = 'all', query = '') {
  return (rows || []).filter(row =>
    (filter === 'all' || row.classification === filter) && _matchesText(row, query));
}

export function filterUnifiOnlyRows(rows = [], query = '', state = 'all',
                                    network = '', type = 'all') {
  return (rows || []).filter(row => {
    if (!_matchesState(row, state) || !_matchesNetwork(row, network)) return false;
    if (!matchesDeviceType(row, type)) return false;
    return _matchesText(row, query);
  });
}

export function filterCandidates(candidates = [], query = '') {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return candidates || [];
  return (candidates || []).filter(candidate => [
    candidate.name, candidate.category, candidate.port,
    ...(candidate.evidence || []), candidate.parent?.name,
  ].filter(value => value !== null && value !== undefined)
    .join(' ').toLowerCase().includes(needle));
}

export function summarizeNetworkComparison(result) {
  if (result?.summary) return result.summary;
  const hosts = result?.hosts || [];
  const services = result?.services || [];
  const count = (rows, classification) =>
    rows.filter(row => row.classification === classification).length;
  const summary = {
    hosts_discovered: hosts.length,
    services_discovered: services.length,
    inventory_devices: 0,
    inventory_services: 0,
    unifi_only: (result?.unifi_only || []).length,
  };
  for (const key of ['matched', 'plausible', 'shared', 'ambiguous', 'unmatched', 'unverified']) {
    summary[`hosts_${key}`] = count(hosts, key);
  }
  for (const key of ['matched', 'plausible', 'ambiguous', 'unmatched', 'unverified']) {
    summary[`services_${key}`] = count(services, key);
  }
  return summary;
}
