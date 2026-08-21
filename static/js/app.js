const API = {
  async get(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Erro na requisicao');
    return data;
  },
  async post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Erro na requisicao');
    return data;
  }
};

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icons = {
    success: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4 12 14.01l-3-3"/></svg>',
    error: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
    info: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'
  };
  toast.innerHTML = `${icons[type] || icons.info}<span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function showLoading(text = 'Carregando...') {
  const overlay = document.getElementById('loading-overlay');
  if (!overlay) return;
  overlay.querySelector('.loading-text').textContent = text;
  overlay.style.display = 'flex';
}

function hideLoading() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.style.display = 'none';
}

function formatPriority(priority) {
  const map = {
    urgent: { label: 'Urgente', class: 'badge-red' },
    high: { label: 'Alta', class: 'badge-red' },
    medium: { label: 'Media', class: 'badge-yellow' },
    low: { label: 'Baixa', class: 'badge-gray' },
    none: { label: 'Nenhuma', class: 'badge-gray' }
  };
  const p = map[priority] || map.none;
  return `<span class="badge ${p.class}">${p.label}</span>`;
}

function formatState(group) {
  const map = {
    backlog: { label: 'Backlog', class: 'badge-gray' },
    unstarted: { label: 'A Fazer', class: 'badge-yellow' },
    started: { label: 'Em Andamento', class: 'badge-red' },
    completed: { label: 'Concluido', class: 'badge-green' },
    cancelled: { label: 'Cancelado', class: 'badge-gray' }
  };
  const s = map[group] || { label: group, class: 'badge-gray' };
  return `<span class="badge ${s.class}">${s.label}</span>`;
}

class TagsInput {
  constructor(container, options = {}) {
    this.container = container;
    this.tags = [];
    this.options = options;
    this.render();
  }

  render() {
    this.container.innerHTML = '';
    this.tags.forEach(tag => {
      const el = document.createElement('span');
      el.className = 'tag';
      el.innerHTML = `${tag}<span class="tag-remove" data-tag="${tag}">&times;</span>`;
      this.container.appendChild(el);
    });
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'tags-input';
    input.placeholder = this.options.placeholder || 'Pressione Enter para adicionar...';
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        this.addTag(input.value);
        input.value = '';
      }
    });
    this.container.appendChild(input);
    this.container.addEventListener('click', (e) => {
      if (e.target.classList.contains('tag-remove')) {
        this.removeTag(e.target.dataset.tag);
      }
    });
  }

  addTag(value) {
    const tag = value.trim();
    if (tag && !this.tags.includes(tag)) {
      this.tags.push(tag);
      this.render();
    }
  }

  removeTag(tag) {
    this.tags = this.tags.filter(t => t !== tag);
    this.render();
  }

  getValues() {
    return [...this.tags];
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-link').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPath || (currentPath === '/' && href === '/')) {
      link.classList.add('active');
    }
  });
});
