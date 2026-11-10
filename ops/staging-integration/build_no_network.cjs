const net = require('node:net');
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function(...args) {
  const first = args[0];
  if ((first && typeof first === 'object' && typeof first.path === 'string') ||
      (typeof first === 'string' && first.includes('/'))) {
    return connect.apply(this, args);
  }
  throw new Error('Isolated review: outbound TCP disabled');
};
globalThis.fetch = async () => { throw new Error('Isolated review: fetch disabled'); };
