// Lets a form creator add their own questions on the index page, each
// with its own answer type. Rows are cloned from a <template> so the
// server can read them back as repeated custom_label/custom_type/
// custom_options fields (see _parse_custom_questions in app.py).
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('custom-questions-list');
  const template = document.getElementById('custom-question-template');
  const addBtn = document.getElementById('add-custom-question');
  if (!container || !template || !addBtn) return;

  function bindRow(row) {
    const typeSelect = row.querySelector('.custom-type-select');
    const optionsWrap = row.querySelector('.custom-options-wrap');
    const removeBtn = row.querySelector('.remove-question-btn');

    typeSelect.addEventListener('change', () => {
      optionsWrap.hidden = typeSelect.value !== 'multiple_choice';
    });

    removeBtn.addEventListener('click', () => {
      row.remove();
    });
  }

  function addRow() {
    const fragment = template.content.cloneNode(true);
    const row = fragment.querySelector('.custom-question-row');
    bindRow(row);
    container.appendChild(fragment);
    row.querySelector('.custom-label-input')?.focus();
  }

  addBtn.addEventListener('click', addRow);

  // Start with one empty row so the option is immediately visible/usable.
  addRow();
});
