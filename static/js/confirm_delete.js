// Ask for confirmation before a delete-form submission actually fires,
// since deleting a form also removes all of its responses permanently.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.delete-form').forEach((form) => {
    form.addEventListener('submit', (e) => {
      const title = form.getAttribute('data-confirm-title') || 'this form';
      const ok = window.confirm(
        `Delete "${title}"? This permanently removes the form and all of its responses. This can't be undone.`
      );
      if (!ok) {
        e.preventDefault();
      }
    });
  });
});
