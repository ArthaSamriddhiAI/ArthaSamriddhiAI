// Alpine.js global stores
document.addEventListener('alpine:init', () => {
  Alpine.store('system', {
    health: null,
    killSwitch: null,
    async refresh() {
      this.health = await api.health();
      this.killSwitch = await api.getKillSwitch();
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
