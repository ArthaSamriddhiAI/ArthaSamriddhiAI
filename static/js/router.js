// Hash-based SPA router for Alpine.js
function app() {
  return {
    screen: 'dashboard',
    params: {},
    helpOpen: false,
    helpKey: '',

    init() {
      this.parseHash();
      window.addEventListener('hashchange', () => this.parseHash());
      Alpine.store('system').refresh();
      setInterval(() => Alpine.store('system').refresh(), 30000);
    },

    parseHash() {
      const hash = window.location.hash.replace('#/', '') || 'dashboard';
      const parts = hash.split('/');
      this.screen = parts[0];
      this.params = parts[1] ? { id: parts[1] } : {};
    },

    navigate(path) {
      window.location.hash = '#/' + path;
    },

    isActive(s) {
      return this.screen === s;
    },

    openHelp(key) {
      this.helpKey = key;
      this.helpOpen = true;
    }
  };
}
