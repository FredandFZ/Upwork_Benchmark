fetch("/api/app/config").then(response => response.json()).then(config => {
  const strategy = config.package_optimization;
  document.querySelector("#package-status").textContent = `${strategy.optimization_priority}; shared asset: ${strategy.asset_strategy.shared_background}`;
});
