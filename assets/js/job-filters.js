// Apply the dashboard's job filters as soon as a dropdown changes. Without
// JavaScript the form still works through its Apply button.

for (const form of document.querySelectorAll("[data-job-filters]")) {
  for (const select of form.querySelectorAll("select")) {
    select.addEventListener("change", () => form.requestSubmit());
  }
}
