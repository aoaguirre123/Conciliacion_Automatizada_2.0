document.addEventListener('DOMContentLoaded', () => {
    const sidebar = document.querySelector('[data-sidebar]');
    const toggle = document.querySelector('[data-sidebar-toggle]');

    if (!sidebar || !toggle) {
        return;
    }

    const setCollapsed = (collapsed) => {
        sidebar.classList.toggle('sidebar--collapsed', collapsed);
        toggle.setAttribute('aria-expanded', String(!collapsed));
        toggle.setAttribute('aria-label', collapsed ? 'Expandir menu' : 'Contraer menu');
        toggle.innerHTML = `<i data-lucide="${collapsed ? 'chevron-right' : 'chevron-left'}" aria-hidden="true"></i>`;

        if (window.lucide) {
            window.lucide.createIcons({ attrs: { 'stroke-width': 1.8 } });
        }
    };

    toggle.addEventListener('click', () => {
        setCollapsed(!sidebar.classList.contains('sidebar--collapsed'));
    });

    sidebar.querySelectorAll('[data-placeholder]').forEach((link) => {
        link.addEventListener('click', (event) => event.preventDefault());
    });

    if (window.matchMedia('(max-width: 700px)').matches) {
        setCollapsed(true);
    }
});
