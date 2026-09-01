export function leaderboardTotals(ledger) {
  return ledger.reduce((total, row) => ({
    tickets: total.tickets + row.tickets,
    commissions: total.commissions + row.commissions,
  }), { tickets: 0, commissions: 0 });
}

export function metadataAttributes(cachedMetadata) {
  return cachedMetadata.attributes;
}
