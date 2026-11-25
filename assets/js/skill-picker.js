// Skill picker for the job form: type to search for a skill and pick it to add
// it; added skills show underneath as labels with a remove (x) button.
//
// It enhances a native <select multiple name="skills">, which stays the source
// of truth for what's submitted (and is what's shown without JavaScript).

for (const root of document.querySelectorAll("[data-skill-picker]")) {
  initSkillPicker(root);
}

function initSkillPicker(root) {
  const select = root.querySelector("select[multiple]");
  if (!select) return;
  const label = root.querySelector("label");
  const options = Array.from(select.options);
  const baseId = select.id || "skills";
  let matches = [];
  let active = -1;

  const input = document.createElement("input");
  input.type = "text";
  input.id = `${baseId}-search`;
  input.autocomplete = "off";
  input.placeholder = "Search skills, e.g. Python";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", `${baseId}-listbox`);
  input.className =
    "w-full rounded-xl border border-line bg-raised px-3.5 py-2.5 text-sm text-ink transition outline-none placeholder:text-ink-faint focus:border-accent/60 focus:ring-4 focus:ring-accent/15";

  const listbox = document.createElement("ul");
  listbox.id = `${baseId}-listbox`;
  listbox.setAttribute("role", "listbox");
  listbox.hidden = true;
  listbox.className =
    "absolute inset-x-0 top-full z-10 mt-1 max-h-64 overflow-auto rounded-xl border border-line bg-raised py-1 shadow-xl shadow-black/40";

  const search = document.createElement("div");
  search.className = "relative";
  search.append(input, listbox);

  const chips = document.createElement("ul");
  chips.className = "mt-3 flex flex-wrap gap-2 empty:hidden";
  chips.setAttribute("aria-label", "Selected skills");

  const status = document.createElement("p");
  status.className = "sr-only";
  status.setAttribute("aria-live", "polite");

  select.after(search, chips, status);
  select.classList.add("hidden");
  if (label) label.htmlFor = input.id;

  function announce(message) {
    status.textContent = message;
  }

  function renderChips() {
    chips.replaceChildren(...options.filter((option) => option.selected).map(chip));
  }

  function chip(option) {
    const item = document.createElement("li");
    item.className =
      "inline-flex items-center gap-1 rounded-lg border border-accent/40 bg-accent/10 py-1 pr-1 pl-2.5 text-sm text-ink";

    const name = document.createElement("span");
    name.textContent = option.text;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${option.text}`);
    remove.className =
      "grid size-5 cursor-pointer place-items-center rounded text-base leading-none text-ink-muted transition hover:bg-white/10 hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none";
    remove.addEventListener("click", () => {
      option.selected = false;
      renderChips();
      announce(`Removed ${option.text}`);
      input.focus();
    });

    item.append(name, remove);
    return item;
  }

  function openList() {
    const query = input.value.trim().toLowerCase();
    // Names that start with the query come first ("kub" → Kubernetes before
    // Azure Kubernetes Service), then other matches, each alphabetically.
    const available = options.filter(
      (option) => !option.selected && option.text.toLowerCase().includes(query),
    );
    matches = [
      ...available.filter((option) => option.text.toLowerCase().startsWith(query)),
      ...available.filter((option) => !option.text.toLowerCase().startsWith(query)),
    ];
    active = matches.length ? 0 : -1;

    if (!matches.length) {
      const empty = document.createElement("li");
      empty.className = "px-3 py-2 text-sm text-ink-faint";
      empty.textContent = query ? "No matching skills" : "Every skill has been added";
      listbox.replaceChildren(empty);
    } else {
      listbox.replaceChildren(
        ...matches.map((option, index) => {
          const item = document.createElement("li");
          item.id = `${baseId}-option-${index}`;
          item.setAttribute("role", "option");
          item.className = "cursor-pointer px-3 py-2 text-sm text-ink-muted";
          item.textContent = option.text;
          // Keep focus in the search box when an option is clicked.
          item.addEventListener("mousedown", (event) => event.preventDefault());
          item.addEventListener("click", () => add(option));
          item.addEventListener("mousemove", () => {
            active = index;
            highlight();
          });
          return item;
        }),
      );
    }
    listbox.hidden = false;
    input.setAttribute("aria-expanded", "true");
    highlight();
  }

  function closeList() {
    listbox.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function highlight() {
    listbox.querySelectorAll("[role=option]").forEach((item, index) => {
      const isActive = index === active;
      item.setAttribute("aria-selected", String(isActive));
      item.classList.toggle("bg-white/10", isActive);
      item.classList.toggle("text-ink", isActive);
      item.classList.toggle("text-ink-muted", !isActive);
      if (isActive) {
        input.setAttribute("aria-activedescendant", item.id);
        item.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function add(option) {
    option.selected = true;
    input.value = "";
    closeList();
    renderChips();
    announce(`Added ${option.text}`);
    input.focus();
  }

  input.addEventListener("input", () => {
    if (input.value.trim()) openList();
    else closeList();
  });

  input.addEventListener("keydown", (event) => {
    const isOpen = !listbox.hidden;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen) openList();
      else if (matches.length) {
        active = (active + 1) % matches.length;
        highlight();
      }
    } else if (event.key === "ArrowUp" && isOpen && matches.length) {
      event.preventDefault();
      active = (active - 1 + matches.length) % matches.length;
      highlight();
    } else if (event.key === "Enter" && isOpen) {
      // Pick the highlighted skill rather than submitting the form.
      event.preventDefault();
      if (active >= 0) add(matches[active]);
    } else if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      closeList();
    } else if (event.key === "Backspace" && !input.value) {
      const last = options.filter((option) => option.selected).pop();
      if (last) {
        last.selected = false;
        renderChips();
        announce(`Removed ${last.text}`);
      }
    }
  });

  input.addEventListener("blur", closeList);
  renderChips();
}
