self.addEventListener('push', function(event) {
  if (event.data) {
    try {
      const payload = event.data.json();
      const options = {
        body: payload.body || 'มีสัญญาณใหม่เข้ามาแล้ว!',
        icon: 'https://cdn-icons-png.flaticon.com/512/2821/2821637.png',
        badge: 'https://cdn-icons-png.flaticon.com/512/2821/2821637.png',
        vibrate: [100, 50, 100],
        data: {
          symbol: payload.symbol,
          direction: payload.direction
        }
      };
      event.waitUntil(
        self.registration.showNotification(payload.title || 'Forex Signal', options)
      );
    } catch (e) {
      // Fallback text if data is not JSON
      const text = event.data.text();
      event.waitUntil(
        self.registration.showNotification('Forex Signal', {
          body: text,
          icon: 'https://cdn-icons-png.flaticon.com/512/2821/2821637.png'
        })
      );
    }
  }
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  // เมื่อกดเปิดแจ้งเตือน ให้พาผู้ใช้เปิดหน้าเว็บ
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(function(clientList) {
      if (clientList.length > 0) {
        return clientList[0].focus();
      }
      return clients.openWindow('./');
    })
  );
});
