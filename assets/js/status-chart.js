// Hover and keyboard layer for the dashboard's "Applications by status" chart.
// The chart itself is server-rendered (tracker/templates/tracker/partials/
// status_chart.html); this adds a crosshair that snaps to the nearest day and
// a tooltip listing every status for that day.

for (const root of document.querySelectorAll("[data-status-chart]")) {
  initStatusChart(root);
}

function initStatusChart(root) {
  const source = document.getElementById(root.dataset.source);
  if (!source) return;

  /** @type {{days: string[], top: number, series: {label: string, slot: number, counts: number[]}[]}} */
  const data = JSON.parse(source.textContent);
  const plot = root.querySelector("[data-plot]");
  const crosshair = root.querySelector("[data-crosshair]");
  const tooltip = root.querySelector("[data-tooltip]");
  const dotsLayer = root.querySelector("[data-dots]");
  const lastIndex = data.days.length - 1;
  let activeIndex = lastIndex;

  // One dot per series, ringed in the surface colour so it stays legible on a line.
  const dots = data.series.map((series) => {
    const dot = document.createElement("span");
    dot.className =
      "absolute hidden size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--series) ring-2 ring-panel";
    dot.style.setProperty("--series", `var(--chart-${series.slot})`);
    dotsLayer.append(dot);
    return dot;
  });

  function xPercent(index) {
    return lastIndex > 0 ? (index / lastIndex) * 100 : 50;
  }

  function show(index) {
    activeIndex = index;
    const left = xPercent(index);
    crosshair.style.left = `${left}%`;
    crosshair.classList.remove("hidden");

    let cumulative = 0;
    data.series.forEach((series, i) => {
      const count = series.counts[index];
      cumulative += count;
      dots[i].style.left = `${left}%`;
      dots[i].style.top = `${(1 - cumulative / data.top) * 100}%`;
      dots[i].classList.toggle("hidden", count === 0);
    });

    renderTooltip(index, cumulative);
    // Keep the tooltip beside the crosshair, on whichever side has room.
    tooltip.style.left = left > 55 ? "" : `calc(${left}% + 12px)`;
    tooltip.style.right = left > 55 ? `calc(${100 - left}% + 12px)` : "";
    tooltip.classList.remove("hidden");
  }

  function hide() {
    crosshair.classList.add("hidden");
    tooltip.classList.add("hidden");
    for (const dot of dots) dot.classList.add("hidden");
  }

  function renderTooltip(index, total) {
    const title = document.createElement("p");
    title.className = "mb-1.5 text-xs font-medium text-ink";
    title.textContent = data.days[index];

    const list = document.createElement("dl");
    list.className = "space-y-1";
    // Top band first, matching the order they are stacked on screen.
    for (const series of [...data.series].reverse()) {
      list.append(row(series.label, series.counts[index], series.slot));
    }
    list.append(row("Total", total, null));

    tooltip.replaceChildren(title, list);
  }

  function row(label, value, slot) {
    const wrapper = document.createElement("div");
    wrapper.className =
      slot === null
        ? "mt-1.5 flex items-center gap-2 border-t border-line pt-1.5 text-xs"
        : "flex items-center gap-2 text-xs";

    const key = document.createElement("span");
    key.className = "h-0.5 w-2.5 shrink-0 rounded-full bg-(--series)";
    key.style.setProperty("--series", slot === null ? "transparent" : `var(--chart-${slot})`);
    key.setAttribute("aria-hidden", "true");

    const term = document.createElement("dt");
    term.className = "flex-1 text-ink-muted";
    term.textContent = label;

    const amount = document.createElement("dd");
    amount.className = "font-semibold text-ink tabular-nums";
    amount.textContent = String(value);

    wrapper.append(key, term, amount);
    return wrapper;
  }

  plot.addEventListener("pointermove", (event) => {
    const rect = plot.getBoundingClientRect();
    const fraction = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
    show(Math.round(fraction * lastIndex));
  });
  plot.addEventListener("pointerleave", () => {
    if (document.activeElement !== plot) hide();
  });

  plot.addEventListener("focus", () => show(activeIndex));
  plot.addEventListener("blur", hide);
  plot.addEventListener("keydown", (event) => {
    const moves = {
      ArrowLeft: activeIndex - 1,
      ArrowRight: activeIndex + 1,
      Home: 0,
      End: lastIndex,
    };
    if (!(event.key in moves)) return;
    event.preventDefault();
    show(Math.min(Math.max(moves[event.key], 0), lastIndex));
  });
}
