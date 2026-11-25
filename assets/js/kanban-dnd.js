// Drag and drop for the jobs board. Cards are dragged by their handle
// ([data-kanban-handle]); the rest of the card behaves normally, so text can be
// selected and links clicked. Dropping a card on another column changes
// the job's status by submitting the card's own status form, so the server
// does exactly the same checks as when the dropdown is used. The dropdown
// stays the way to move cards from the keyboard or on touch screens (which
// don't support HTML drag and drop).

for (const board of document.querySelectorAll("[data-kanban]")) {
  initKanbanDragAndDrop(board);
}

function initKanbanDragAndDrop(board) {
  const highlight = ["ring-2", "ring-accent/50", "bg-accent/5"];
  let dragged = null;

  // A card can move to any other column except "Not applied" (status ""):
  // a job can't be un-applied for.
  function canDrop(column) {
    if (!dragged || column.dataset.status === "") return false;
    return dragged.closest("[data-kanban-column]") !== column;
  }

  function clearHighlights() {
    for (const column of board.querySelectorAll("[data-kanban-column]")) {
      column.classList.remove(...highlight);
    }
  }

  for (const handle of board.querySelectorAll("[data-kanban-handle]")) {
    const card = handle.closest("[data-kanban-card]");
    handle.addEventListener("dragstart", (event) => {
      dragged = card;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.id);
      // Show the whole card under the pointer, not just the small handle.
      const handleBox = handle.getBoundingClientRect();
      const cardBox = card.getBoundingClientRect();
      event.dataTransfer.setDragImage(
        card,
        handleBox.left - cardBox.left + handleBox.width / 2,
        handleBox.top - cardBox.top + handleBox.height / 2,
      );
      card.classList.add("opacity-50");
    });
    handle.addEventListener("dragend", () => {
      card.classList.remove("opacity-50");
      dragged = null;
      clearHighlights();
    });
  }

  for (const column of board.querySelectorAll("[data-kanban-column]")) {
    column.addEventListener("dragover", (event) => {
      if (!canDrop(column)) return;
      event.preventDefault(); // allow the drop
      event.dataTransfer.dropEffect = "move";
      column.classList.add(...highlight);
    });
    column.addEventListener("dragleave", (event) => {
      if (!column.contains(event.relatedTarget)) column.classList.remove(...highlight);
    });
    column.addEventListener("drop", (event) => {
      event.preventDefault();
      clearHighlights();
      if (!canDrop(column)) return;
      const form = dragged.querySelector("form");
      form.querySelector("select[name=status]").value = column.dataset.status;
      form.requestSubmit();
    });
  }
}
