/** Pure reconciliation view helpers: filtering and compact summaries. */
export const FILTERS = [
  { value: 'all', label: 'All discoveries' },
  { value: 'matched', label: 'Matched' },
  { value: 'unmatched', label: 'Unmatched' },
  { value: 'excluded', label: 'Excluded' },
  { value: 'uncertain', label: 'Uncertain' },
];

const FILTER_CLASSIFICATIONS = {
  matched: ['matched'],
  unmatched: ['missing_inventory'],
  excluded: ['excluded'],
  uncertain: ['duplicate', 'older_observation'],
};

/** Map a discovered-row classification to one summary/filter category. */
export function filterClassification(classification) {
  for (const [filter, values] of Object.entries(FILTER_CLASSIFICATIONS)) {
    if (values.includes(classification)) return filter;
  }
  return 'other';
}

/** Filter discovered rows by category and a container/application search string. */
export function filterContainers(rows = [], filter = 'all', query = '') {
  const needle = String(query || '').trim().toLowerCase();
  return (rows || []).filter(row => {
    const classifications = FILTER_CLASSIFICATIONS[filter];
    if (filter !== 'all' && !(classifications || []).includes(row.classification)) return false;
    if (!needle) return true;
    return `${row.container_name || ''} ${row.app_name || ''}`
      .toLowerCase()
      .includes(needle);
  });
}

/** Use server counts when available; tolerate older/partial report fixtures. */
export function summarizeReport(report) {
  if (report?.summary) return report.summary;
  const rows = report?.containers || [];
  const inventory = report?.inventory || [];
  const count = classification => rows.filter(row => row.classification === classification).length;
  return {
    matched: count('matched'),
    unmatched: count('missing_inventory'),
    excluded: count('excluded'),
    uncertain: count('duplicate') + count('older_observation'),
    not_seen: inventory.length,
  };
}

/** Count field values that actually change in a reviewed bulk plan. */
export function changedFieldCount(plan) {
  return (plan?.applications || []).reduce((total, item) =>
    total + (item.fields || []).filter(field =>
      String(field.before ?? '') !== String(field.after ?? '')).length, 0);
}
