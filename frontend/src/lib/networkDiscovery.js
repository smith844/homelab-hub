/** Pure network-discovery filtering and summary helpers. */
export const TERMINAL_STATUSES = ['completed', 'partial', 'failed'];

export const COMPARISON_FILTERS = [
  { value: 'all', label: 'All observations' },
  { value: 'matched', label: 'Matched inventory' },
  { value: 'unmatched', label: 'Unmatched' },
  { value: 'uncertain', label: 'Uncertain / unverified' },
  { value: 'unknown', label: 'Unknown / other' },
];

export function scanIsTerminal(status) {
  return TERMINAL_STATUSES.includes(status);
}

export function comparisonCategory(classification) {
  if (classification === 'matched') return 'matched';
  if (classification === 'unmatched') return 'unmatched';
  if (classification === 'duplicate' || classification === 'unverified') return 'uncertain';
  return 'other';
}

export function filterComparisonRows(rows = [], filter = 'all', query = '') {
  const needle = String(query || '').trim().toLowerCase();
  const desired = filter === 'unknown' ? 'other' : filter;
  return (rows || []).filter(row => {
    if (filter !== 'all' && comparisonCategory(row.classification) !== desired) return false;
    if (!needle) return true;
    return [
      row.ip,
      row.port,
      row.name,
      row.classification,
      ...(row.matches || []).map(match => match.name),
    ].filter(value => value !== null && value !== undefined).join(' ').toLowerCase().includes(needle);
  });
}

export function filterScanRows(rows = [], query = '') {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return rows || [];
  return (rows || []).filter(row => [
    row.ip,
    row.hostname,
    row.mac,
    row.mac_address,
    row.vendor,
    row.os,
    row.port,
    row.service_name,
    row.service_version,
    row.state,
  ].filter(value => value !== null && value !== undefined).join(' ').toLowerCase().includes(needle));
}

export function summarizeScan(scan) {
  if (!scan) {
    return {status: 'idle', hosts: 0, services: 0, hosts_up: 0, hosts_down: 0, warnings: 0, complete: false};
  }
  const hosts = Array.isArray(scan.hosts) ? scan.hosts : [];
  const results = Array.isArray(scan.results) ? scan.results : [];
  return {
    status: scan.status || 'unknown',
    hosts: Array.isArray(scan.hosts)
      ? hosts.length
      : new Set(results.map(row => row.ip).filter(Boolean)).size,
    services: results.filter(row => row.port !== null && row.port !== undefined).length,
    hosts_up: Number.isInteger(scan.hosts_up) ? scan.hosts_up : 0,
    hosts_down: Number.isInteger(scan.hosts_down) ? scan.hosts_down : 0,
    warnings: Array.isArray(scan.warnings) ? scan.warnings.length : 0,
    complete: scan.complete === true,
  };
}

export function discoveryCategories(rows = []) {
  return rows.reduce((counts, row) => {
    const category = comparisonCategory(row.classification);
    counts[category] = (counts[category] || 0) + 1;
    return counts;
  }, {matched: 0, unmatched: 0, uncertain: 0, other: 0});
}
