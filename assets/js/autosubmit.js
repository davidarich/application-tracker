// Submit a form as soon as a select marked data-autosubmit changes (e.g. the
// status dropdowns on the jobs board), and hide the Save buttons marked
// data-autosubmit-fallback, which are only needed without JavaScript.

for (const select of document.querySelectorAll("select[data-autosubmit]")) {
  select.addEventListener("change", () => select.form?.requestSubmit());
}
for (const button of document.querySelectorAll("[data-autosubmit-fallback]")) {
  button.hidden = true;
}
