// Alpine.js global stores
document.addEventListener('alpine:init', () => {
  Alpine.store('system', {
    health: null,
    async refresh() {
      this.health = await api.health();
    }
  });

  Alpine.store('notifications', {
    items: [],
    add(type, message) {
      const id = Date.now();
      this.items.push({ id, type, message });
      setTimeout(() => { this.items = this.items.filter(n => n.id !== id); }, 4000);
    }
  });
});
