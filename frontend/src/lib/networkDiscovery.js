/** Pure network-wide discovery filtering and summary helpers. */
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

export const TERMINAL_STATUSES = ['completed', 'partial', 'failed'];

export function scanIsTerminal(status) {
  return TERMINAL_STATUSES.includes(status);
}

function _candidateText(row) {
  const candidates = [...(row.candidates || []), ...(row.service_candidates || [])];
  return candidates.map(candidate => [
    candidate.name,
    candidate.category,
    ...(candidate.evidence || []),
  ].join(' ')).join(' ');
}

function _matches(row, filter, query) {
  if (filter !== 'all' && row.classification !== filter) return false;
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  return [
    row.ip,
    row.hostname,
    row.mac,
    row.vendor,
    row.os,
    row.port,
    row.service_name,
    row.service_version,
    row.classification,
    ...(row.evidence || []),
    _candidateText(row),
  ].filter(value => value !== null && value !== undefined).join(' ').toLowerCase().includes(needle);
}

export function filterHostRows(rows = [], filter = 'all', query = '') {
  return (rows || []).filter(row => _matches(row, filter, query));
}

export function filterServiceRows(rows = [], filter = 'all', query = '') {
  return (rows || []).filter(row => _matches(row, filter, query));
}

export function primaryCandidate(row) {
  return row?.candidates?.[0] || null;
}

export function candidateCount(row) {
  return (row?.candidates?.length || 0) + (row?.service_candidates?.length || 0);
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
  };
  for (const key of ['matched', 'plausible', 'shared', 'ambiguous', 'unmatched', 'unverified']) {
    summary[`hosts_${key}`] = count(hosts, key);
  }
  for (const key of ['matched', 'plausible', 'ambiguous', 'unmatched', 'unverified']) {
    summary[`services_${key}`] = count(services, key);
  }
  return summary;
}
