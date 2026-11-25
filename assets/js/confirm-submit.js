// Ask before submitting a form marked with data-confirm (e.g. the delete
// buttons on the edit pages). Without JavaScript the form submits directly.

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.dataset.confirm) return;
  if (!window.confirm(form.dataset.confirm)) event.preventDefault();
});
