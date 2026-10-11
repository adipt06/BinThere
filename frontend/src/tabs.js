/** One tab controller keeps view state intact and supports keyboard navigation. */
export function initializeTabs({ resizeMap, suspendNavigation }) {
  const names = ['navigation', 'ai', 'community'];
  const panel = document.getElementById('bin-panel');
  function selectView(name, focus = false) {
    if (!names.includes(name)) return;
    for (const item of names) {
      const tab = document.getElementById(`${item}-tab`), active = item === name;
      document.getElementById(`${item}-view`).hidden = !active;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
    }
    panel.classList.remove('collapsed');
    document.getElementById('map-status').hidden = true;
    const toggle = document.getElementById('panel-toggle');
    toggle.setAttribute('aria-expanded', 'true'); toggle.textContent = 'Hide controls';
    suspendNavigation(); resizeMap();
    document.querySelector('.panel-content').scrollTop = 0;
    if (focus) document.getElementById(`${name}-tab`).focus();
  }
  names.forEach((name, index) => {
    const tab = document.getElementById(`${name}-tab`);
    tab.onclick = () => selectView(name);
    tab.onkeydown = event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % names.length;
      if (event.key === 'ArrowLeft') next = (index + names.length - 1) % names.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = names.length - 1;
      if (next !== undefined) { event.preventDefault(); selectView(names[next], true); }
    };
  });
  return selectView;
}
