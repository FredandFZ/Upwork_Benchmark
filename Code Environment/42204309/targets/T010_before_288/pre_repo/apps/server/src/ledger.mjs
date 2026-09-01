export function listOwnedAssets(rows, account) {
  return rows.filter((row) => row.account === account);
}

export function dashboardCount(rows, account) {
  return listOwnedAssets(rows, account).length;
}
