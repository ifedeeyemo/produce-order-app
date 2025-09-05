function setupPricing(catalog) {
  const itemSelect = document.getElementById('item');
  const qtyInput = document.getElementById('quantity');
  const unitPriceSpan = document.getElementById('unit_price');
  const lineTotalSpan = document.getElementById('line_total');

  function recalc() {
    const item = itemSelect.value;
    const qty = parseFloat(qtyInput.value || '0');
    const unit = parseFloat((catalog[item] || 0));
    if (!isNaN(unit)) {
      unitPriceSpan.textContent = unit.toFixed(2);
      const total = qty * unit;
      lineTotalSpan.textContent = isNaN(total) ? '0.00' : total.toFixed(2);
    } else {
      unitPriceSpan.textContent = '0.00';
      lineTotalSpan.textContent = '0.00';
    }
  }

  itemSelect.addEventListener('change', recalc);
  qtyInput.addEventListener('input', recalc);
  recalc();
}
