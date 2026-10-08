type SortKey = "id" | "title" | "area" | "lean" | "date" | "manuscripts";

function compare(left: HTMLTableRowElement, right: HTMLTableRowElement, key: SortKey): number {
  switch (key) {
    case "id":
      return (left.dataset.id ?? "").localeCompare(right.dataset.id ?? "");
    case "title":
      return (left.dataset.title ?? "").localeCompare(right.dataset.title ?? "");
    case "area":
      return (left.dataset.area ?? "").localeCompare(right.dataset.area ?? "");
    case "lean":
      return Number(left.dataset.leanRank) - Number(right.dataset.leanRank);
    case "date":
      return (left.dataset.date ?? "").localeCompare(right.dataset.date ?? "");
    case "manuscripts":
      return Number(left.dataset.manuscripts) - Number(right.dataset.manuscripts);
    default: {
      const exhaustive: never = key;
      return exhaustive;
    }
  }
}

function isSortKey(value: string): value is SortKey {
  switch (value) {
    case "id":
    case "title":
    case "area":
    case "lean":
    case "date":
    case "manuscripts":
      return true;
    default:
      return false;
  }
}

export function mountTable(): void {
  const table = document.querySelector<HTMLTableElement>("[data-family-table]");
  const tbody = table?.querySelector("tbody");
  const search = document.querySelector<HTMLInputElement>("#family-search");
  const area = document.querySelector<HTMLSelectElement>("#area-filter");
  const lens = document.querySelector<HTMLSelectElement>("#lens-filter");
  const lean = document.querySelector<HTMLSelectElement>("#lean-filter");
  const shown = document.querySelector<HTMLElement>("#shown-count");
  if (!table || !tbody || !search || !area || !lens || !lean || !shown) {
    return;
  }

  let key: SortKey = "id";
  let direction: 1 | -1 = 1;

  const apply = () => {
    const query = search.value.trim().toLowerCase();
    const areaValue = area.value;
    const lensValue = lens.value;
    const leanValue = lean.value;
    let visible = 0;
    for (const row of tbody.querySelectorAll<HTMLTableRowElement>("tr")) {
      const areas = (row.dataset.areas ?? "").split("|");
      const lenses = (row.dataset.lenses ?? "").split("|").filter((item) => item !== "");
      const matchesQuery = query === "" || (row.textContent ?? "").toLowerCase().includes(query);
      const matchesArea = areaValue === "" || areas.includes(areaValue);
      const matchesLens = lensValue === "" || lenses.includes(lensValue);
      const matchesLean = leanValue === "" || row.dataset.lean === leanValue;
      const keep = matchesQuery && matchesArea && matchesLens && matchesLean;
      row.hidden = !keep;
      if (keep) {
        visible += 1;
      }
    }
    const total = tbody.querySelectorAll("tr").length;
    shown.textContent = `Showing ${visible} of ${total}`;
  };

  const sort = () => {
    const rows = [...tbody.querySelectorAll<HTMLTableRowElement>("tr")];
    rows.sort((left, right) => compare(left, right, key) * direction);
    for (const row of rows) {
      tbody.appendChild(row);
    }
    for (const header of table.querySelectorAll<HTMLElement>("th[data-sort]")) {
      const headerKey = header.dataset.sort;
      header.setAttribute("aria-sort", headerKey === key ? (direction === 1 ? "ascending" : "descending") : "none");
    }
  };

  for (const button of table.querySelectorAll<HTMLButtonElement>("button[data-sort]")) {
    button.addEventListener("click", () => {
      const next = button.dataset.sort ?? "";
      if (!isSortKey(next)) {
        return;
      }
      if (next === key) {
        direction = direction === 1 ? -1 : 1;
      } else {
        key = next;
        direction = 1;
      }
      sort();
    });
  }

  search.addEventListener("input", apply);
  area.addEventListener("change", apply);
  lens.addEventListener("change", apply);
  lean.addEventListener("change", apply);
  const reset = document.querySelector<HTMLButtonElement>("#filter-reset");
  reset?.addEventListener("click", () => {
    search.value = "";
    area.value = "";
    lens.value = "";
    lean.value = "";
    apply();
  });
  sort();
  apply();
}
