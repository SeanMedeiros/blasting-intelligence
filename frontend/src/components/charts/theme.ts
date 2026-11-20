/** Chart tokens. Categorical order is fixed (blue, orange, aqua) and was validated
 *  for CVD separation and contrast on the card surface #131c2b. */
export const chart = {
  surface: "#131c2b",
  grid: "#22304a",
  axis: "#33445f",
  tick: "#8794a8",
  text: "#e6ebf2",
  series: ["#3987e5", "#d95926", "#199e70"],
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  reference: "#b6c0cf",
};

export const axisProps = {
  stroke: chart.axis,
  tick: { fill: chart.tick, fontSize: 11 },
  tickLine: false,
} as const;
