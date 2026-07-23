(function (root) {
  "use strict";

  function bracket(grid, value) {
    if (value <= grid[0]) return [grid[0], grid[0], 0];
    if (value >= grid[grid.length - 1]) {
      return [grid[grid.length - 1], grid[grid.length - 1], 0];
    }
    let upper = 1;
    while (grid[upper] < value) upper += 1;
    const low = grid[upper - 1], high = grid[upper];
    return [low, high, (value - low) / (high - low)];
  }

  function basis(model, lengthFactor, k, n) {
    const s = model.control_scaling;
    const l = (lengthFactor - s.length_factor.center) / s.length_factor.scale;
    const kk = (k - s.k.center) / s.k.scale;
    const nn = (n - s.n.center) / s.n.scale;
    return [1, l, kk, nn, l*l, kk*kk, nn*nn, l*kk, l*nn, kk*nn];
  }

  function dot(left, right) {
    return left.reduce((sum, value, index) => sum + value * right[index], 0);
  }

  function evaluateRoundControl(model, input) {
    const [m0, m1, tm] = bracket(model.mouth_grid_mm, input.mouth_mm);
    const [c0, c1, tc] = bracket(model.coverage_grid_deg, input.coverage_deg);
    let corners = [
      [c0, m0, (1-tc)*(1-tm)], [c0, m1, (1-tc)*tm],
      [c1, m0, tc*(1-tm)], [c1, m1, tc*tm]
    ].filter(item => item[2] > 0);
    if (!corners.length) corners = [[c0, m0, 1]];
    const reference = corners.reduce((sum, item) =>
      sum + model.reference_length_mm[
        `${Math.trunc(item[0])}deg-${Math.trunc(item[1])}mm`] * item[2], 0);
    const x = basis(model, input.length_mm/reference, input.k, input.n);
    const output = {};
    model.diagnostics.forEach(name => {
      output[name] = corners.reduce((sum, item) => {
        const id = `${Math.trunc(item[0])}deg-${Math.trunc(item[1])}mm`;
        return sum + item[2] * dot(model.cells[id].coefficients[name], x);
      }, 0);
    });
    return output;
  }

  root.evaluateRoundControl = evaluateRoundControl;
  if (typeof module !== "undefined") module.exports = { evaluateRoundControl };
})(typeof globalThis !== "undefined" ? globalThis : this);
