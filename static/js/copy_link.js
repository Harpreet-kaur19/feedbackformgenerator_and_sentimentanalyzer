// Generic "copy link" behavior. Any button with data-copy-target="<id>"
// copies the text content (or value, for inputs) of the element with that
// id, and briefly flips its own label to confirm the copy worked.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.getAttribute('data-copy-target');
      const target = document.getElementById(targetId);
      if (!target) return;

      const text = 'value' in target ? target.value : target.textContent;

      navigator.clipboard.writeText(text).then(() => {
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('is-copied');
        setTimeout(() => {
          btn.textContent = original;
          btn.classList.remove('is-copied');
        }, 1500);
      });
    });
  });
});
